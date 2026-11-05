import os

# Use a throwaway database for tests. This must happen BEFORE importing app.
os.environ["DATABASE_URL"] = "sqlite:///test_trades.db"

import pytest
import redis

import app as app_module


class FakeCache:
    """A pretend Redis that stores things in a dictionary."""

    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None):
        self.data[key] = value

    def delete(self, key):
        self.data.pop(key, None)


class BrokenCache:
    """A pretend Redis that is down: every call fails."""

    def get(self, key):
        raise redis.RedisError("redis is down")

    def set(self, key, value, ex=None):
        raise redis.RedisError("redis is down")

    def delete(self, key):
        raise redis.RedisError("redis is down")


@pytest.fixture
def client():
    # Runs before EVERY test: empty database + fresh fake cache
    app_module.Base.metadata.drop_all(app_module.engine)
    app_module.Base.metadata.create_all(app_module.engine)
    app_module.cache = FakeCache()
    return app_module.app.test_client()


def add_trade(client, pair="eurusd", side="buy", profit=50):
    return client.post(
        "/trades",
        json={
            "pair": pair,
            "side": side,
            "entry_price": 1.0850,
            "exit_price": 1.0900,
            "profit": profit,
            "note": "test",
        },
    )


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_add_trade(client):
    response = add_trade(client)
    assert response.status_code == 201
    data = response.get_json()
    assert data["pair"] == "EURUSD"  # the app uppercases it
    assert data["profit"] == 50


def test_add_trade_missing_fields(client):
    response = client.post("/trades", json={"pair": "eurusd"})
    assert response.status_code == 400
    assert "missing fields" in response.get_json()["error"]


def test_add_trade_bad_side(client):
    response = add_trade(client, side="hold")
    assert response.status_code == 400


def test_list_trades(client):
    add_trade(client)
    add_trade(client, pair="gbpusd")
    response = client.get("/trades")
    assert response.status_code == 200
    assert len(response.get_json()) == 2


def test_delete_trade(client):
    trade_id = add_trade(client).get_json()["id"]
    response = client.delete(f"/trades/{trade_id}")
    assert response.status_code == 200
    assert client.get("/trades").get_json() == []


def test_delete_missing_trade(client):
    response = client.delete("/trades/999")
    assert response.status_code == 404


def test_stats_empty(client):
    data = client.get("/stats").get_json()
    assert data["total_trades"] == 0
    assert data["best_pair"] is None


def test_stats_values(client):
    add_trade(client, pair="eurusd", profit=50)
    add_trade(client, pair="gbpusd", profit=-50)
    add_trade(client, pair="usdjpy", profit=80)
    data = client.get("/stats").get_json()
    assert data["total_trades"] == 3
    assert data["wins"] == 2
    assert data["losses"] == 1
    assert data["win_rate"] == 66.7
    assert data["total_profit"] == 80
    assert data["best_pair"] == "USDJPY"
    assert data["worst_pair"] == "GBPUSD"


def test_stats_uses_cache(client):
    add_trade(client)
    first = client.get("/stats").get_json()
    second = client.get("/stats").get_json()
    assert first["source"] == "database"
    assert second["source"] == "cache"


def test_cache_cleared_when_trade_added(client):
    add_trade(client, profit=50)
    client.get("/stats")  # fills the cache
    add_trade(client, profit=30)  # should clear the cache
    data = client.get("/stats").get_json()
    assert data["source"] == "database"
    assert data["total_trades"] == 2
    assert data["total_profit"] == 80


def test_app_works_when_redis_is_down(client):
    app_module.cache = BrokenCache()
    add_trade(client)
    response = client.get("/stats")
    assert response.status_code == 200
    assert response.get_json()["source"] == "database"
import json
import os
from datetime import datetime, timezone

import redis
from flask import Flask, jsonify, request
from sqlalchemy import Column, DateTime, Float, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Where is the database? Read from the environment, with a local default.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///trades.db")

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
Base = declarative_base()
# Where is Redis? Also read from the environment.
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
cache = redis.Redis.from_url(
    REDIS_URL, socket_connect_timeout=1, decode_responses=True
)
STATS_KEY = "stats"
STATS_TTL = 300  # keep cached stats for 5 minutes


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True)
    pair = Column(String(20), nullable=False)
    side = Column(String(4), nullable=False)  # "buy" or "sell"
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=False)
    profit = Column(Float, nullable=False)  # positive = win, negative = loss
    note = Column(String(500), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "pair": self.pair,
            "side": self.side,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "profit": self.profit,
            "note": self.note,
            "created_at": self.created_at.isoformat(),
        }


# Create the "trades" table if it doesn't exist yet
Base.metadata.create_all(engine)

def cache_get(key):
    try:
        return cache.get(key)
    except redis.RedisError:
        return None  # Redis down? Act like nothing is cached.


def cache_set(key, value, ttl):
    try:
        cache.set(key, value, ex=ttl)  # ex = expire after ttl seconds
    except redis.RedisError:
        pass


def cache_delete(key):
    try:
        cache.delete(key)
    except redis.RedisError:
        pass


def calculate_stats(session):
    trades = session.query(Trade).all()
    total = len(trades)
    if total == 0:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "total_profit": 0.0,
            "best_pair": None,
            "worst_pair": None,
        }

    wins = sum(1 for t in trades if t.profit > 0)
    losses = sum(1 for t in trades if t.profit < 0)

    profit_by_pair = {}
    for t in trades:
        profit_by_pair[t.pair] = profit_by_pair.get(t.pair, 0) + t.profit

    return {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / total * 100, 1),
        "total_profit": round(sum(t.profit for t in trades), 2),
        "best_pair": max(profit_by_pair, key=profit_by_pair.get),
        "worst_pair": min(profit_by_pair, key=profit_by_pair.get),
    }
app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.post("/trades")
def add_trade():
    data = request.get_json(silent=True) or {}

    required = ["pair", "side", "entry_price", "exit_price", "profit"]
    missing = [field for field in required if field not in data]
    if missing:
        return jsonify(error=f"missing fields: {missing}"), 400

    if data["side"] not in ("buy", "sell"):
        return jsonify(error="side must be 'buy' or 'sell'"), 400

    try:
        entry = float(data["entry_price"])
        exit_ = float(data["exit_price"])
        profit = float(data["profit"])
    except (TypeError, ValueError):
        return jsonify(error="prices and profit must be numbers"), 400

    session = Session()
    try:
        trade = Trade(
            pair=str(data["pair"]).upper(),
            side=data["side"],
            entry_price=entry,
            exit_price=exit_,
            profit=profit,
            note=data.get("note", ""),
        )
        session.add(trade)
        session.commit()
        cache_delete(STATS_KEY)
        return jsonify(trade.to_dict()), 201
    finally:
        session.close()


@app.get("/trades")
def list_trades():
    session = Session()
    try:
        trades = session.query(Trade).order_by(Trade.id.desc()).all()
        return jsonify([t.to_dict() for t in trades])
    finally:
        session.close()

@app.delete("/trades/<int:trade_id>")
def delete_trade(trade_id):
    session = Session()
    try:
        trade = session.get(Trade, trade_id)
        if trade is None:
            return jsonify(error="trade not found"), 404
        session.delete(trade)
        session.commit()
    finally:
        session.close()
    cache_delete(STATS_KEY)
    return jsonify(message="deleted")


@app.get("/stats")
def stats():
    cached = cache_get(STATS_KEY)
    if cached:
        result = json.loads(cached)
        result["source"] = "cache"
        return jsonify(result)

    session = Session()
    try:
        result = calculate_stats(session)
    finally:
        session.close()

    cache_set(STATS_KEY, json.dumps(result), STATS_TTL)
    result["source"] = "database"
    return jsonify(result)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
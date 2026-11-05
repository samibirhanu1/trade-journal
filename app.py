import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from sqlalchemy import Column, DateTime, Float, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Where is the database? Read from the environment, with a local default.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///trades.db")

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
Base = declarative_base()


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
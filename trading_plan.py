# trading_plan.py
"""
New simpler strategy – EMA 200 trend + ATR stops.
Long only. No short. No leverage.

Entry rules:
  1. Price is above the 200-period EMA
  2. The distance between price and the 200 EMA is more than 1 %
  3. We have not lost in the last 10 candles (cooldown)
  4. We have not already taken 2 trades today

Exit rules:
  Stop-loss  = entry - 1.5 × ATR
  Take-profit = entry + 3.0 × ATR
  (plus a simple trailing stop once price has moved 1.5 × ATR in profit)
"""

from typing import Optional, List, Dict
from datetime import datetime, timezone

import chart_math
import my_settings


def _atr(candles: list, length: int = 14) -> Optional[float]:
    """Average True Range – how much the price normally moves."""
    if len(candles) < length + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if len(trs) < length:
        return None
    return sum(trs[-length:]) / length


class CoinPurchase:
    """
    Remembers one open purchase and decides when to sell.
    Stops and targets are set with ATR at entry time.
    """

    def __init__(
        self,
        coin_name: str,
        buy_price: float,
        amount_of_coin: float,
        stop_price: float = None,
        target_price: float = None,
    ) -> None:
        self.coin_name = coin_name
        self.buy_price = buy_price
        self.amount_of_coin = amount_of_coin

        # If ATR values were supplied we use them, otherwise fall back to settings
        if stop_price is not None:
            self.emergency_exit_price = stop_price
        else:
            self.emergency_exit_price = buy_price * (1 - my_settings.hard_stop_percent)

        if target_price is not None:
            self.dream_sell_price = target_price
        else:
            self.dream_sell_price = buy_price * (1 + my_settings.take_profit_percent)

        self.highest_price_seen = buy_price
        self.stop_order_id: Optional[int] = None
        self.initial_stop = self.emergency_exit_price

    def follow_price_up(self, current_price: float) -> None:
        """Simple trailing: once we are 1.5 × the original risk in profit, trail."""
        self.highest_price_seen = max(self.highest_price_seen, current_price)
        risk = self.buy_price - self.initial_stop
        if risk <= 0:
            return
        # Activate trailing only after 1.5R profit
        if current_price >= self.buy_price + 1.5 * risk:
            trail = self.highest_price_seen - risk
            self.emergency_exit_price = max(self.emergency_exit_price, trail)

    def should_i_sell(self, current_price: float) -> str:
        if current_price >= self.dream_sell_price:
            return "reached my profit target"
        if current_price <= self.emergency_exit_price:
            if self.emergency_exit_price > self.initial_stop:
                return "trailing stop caught the fall"
            return "emergency exit, cut the loss"
        return ""

    def to_dict(self) -> dict:
        return {
            "coin_name": self.coin_name,
            "buy_price": self.buy_price,
            "amount_of_coin": self.amount_of_coin,
            "emergency_exit_price": self.emergency_exit_price,
            "dream_sell_price": self.dream_sell_price,
            "highest_price_seen": self.highest_price_seen,
            "stop_order_id": self.stop_order_id,
            "initial_stop": self.initial_stop,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CoinPurchase":
        obj = cls(
            data["coin_name"],
            data["buy_price"],
            data["amount_of_coin"],
            stop_price=data.get("emergency_exit_price"),
            target_price=data.get("dream_sell_price"),
        )
        obj.highest_price_seen = data.get("highest_price_seen", data["buy_price"])
        obj.stop_order_id = data.get("stop_order_id")
        obj.initial_stop = data.get("initial_stop", obj.emergency_exit_price)
        return obj


class MyPlan:
    """
    EMA-200 trend + ATR stop/target strategy.
    """

    plan_name = "ema200_atr"

    def __init__(self) -> None:
        self.last_loss_index: int = -9999          # candle index of last loss
        self.trades_today: Dict[str, int] = {}     # date_str → count
        self.cooldown_candles: int = 10

    def _ema(self, prices: List[float], length: int) -> Optional[float]:
        if len(prices) < length:
            return None
        # Simple approximation of EMA using the last `length` prices
        # (good enough and keeps us independent of extra libraries)
        k = 2 / (length + 1)
        ema = prices[-length]
        for p in prices[-length + 1:]:
            ema = p * k + ema * (1 - k)
        return ema

    def should_i_buy(self, candles: list) -> str:
        if len(candles) < 220:          # need enough history for 200 EMA + ATR
            return ""

        prices = [c["close"] for c in candles]
        price_now = prices[-1]
        idx = len(candles) - 1

        # 1. Cooldown after a loss
        if idx - self.last_loss_index < self.cooldown_candles:
            return ""

        # 2. Max 2 trades per calendar day
        day = datetime.utcfromtimestamp(candles[-1]["open_time"] / 1000).strftime("%Y-%m-%d")
        if self.trades_today.get(day, 0) >= 2:
            return ""

        # 3. 200 EMA trend filter
        ema200 = self._ema(prices, 200)
        if ema200 is None or price_now <= ema200:
            return ""

        # 4. EMA spread must be > 1 %
        spread = (price_now - ema200) / ema200
        if spread < 0.01:
            return ""

        # 5. ATR must be available
        atr = _atr(candles, 14)
        if atr is None or atr <= 0:
            return ""

        return "BUY"

    def record_loss(self, candle_index: int) -> None:
        """Called by the outside world when a trade loses."""
        self.last_loss_index = candle_index

    def record_trade_taken(self, candle_time_ms: int) -> None:
        day = datetime.utcfromtimestamp(candle_time_ms / 1000).strftime("%Y-%m-%d")
        self.trades_today[day] = self.trades_today.get(day, 0) + 1


# Keep the same registry interface
MY_PLANS = {
    "ema200_atr": MyPlan(),
    "trend_rsi_volume_bollinger": MyPlan(),   # safety alias so old calls do not crash
}


def pick_plan(name: str) -> MyPlan:
    if name not in MY_PLANS:
        # fall back to the new plan
        return MY_PLANS["ema200_atr"]
    return MY_PLANS[name]
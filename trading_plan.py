"""
trading_plan.py
---------------
Simplified strategy (Option A):
  BUY only if BOTH conditions are true:
    1. Trend is UP   (price above its moving average)
    2. RSI is in a healthy range (not overbought, not too weak)

  SELL when:
    - Take-profit is hit, or
    - Trailing stop is hit, or
    - Hard stop is hit
"""

from typing import Optional

import chart_math
import my_settings


class CoinPurchase:
    """Remembers one open purchase and decides when to sell."""

    def __init__(self, coin_name: str, buy_price: float, amount_of_coin: float) -> None:
        self.coin_name = coin_name
        self.buy_price = buy_price
        self.amount_of_coin = amount_of_coin

        self.emergency_exit_price = buy_price * (1 - my_settings.hard_stop_percent)
        self.dream_sell_price = buy_price * (1 + my_settings.take_profit_percent)
        self.highest_price_seen = buy_price

    def follow_price_up(self, current_price: float) -> None:
        self.highest_price_seen = max(self.highest_price_seen, current_price)
        trailing = self.highest_price_seen * (1 - my_settings.trailing_stop_percent)
        self.emergency_exit_price = max(self.emergency_exit_price, trailing)

    def should_i_sell(self, current_price: float) -> str:
        if current_price >= self.dream_sell_price:
            return "reached my profit target"
        if current_price <= self.emergency_exit_price:
            if self.emergency_exit_price > self.buy_price * (1 - my_settings.hard_stop_percent):
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
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CoinPurchase":
        obj = cls(
            data["coin_name"],
            data["buy_price"],
            data["amount_of_coin"],
        )
        obj.emergency_exit_price = data.get("emergency_exit_price", obj.emergency_exit_price)
        obj.dream_sell_price = data.get("dream_sell_price", obj.dream_sell_price)
        obj.highest_price_seen = data.get("highest_price_seen", data["buy_price"])
        return obj


class MyPlan:
    """Simplified trend + RSI strategy."""

    plan_name = "trend_rsi_simple"

    def should_i_buy(self, candles: list) -> str:
        prices = [c["close"] for c in candles]

        need = max(my_settings.trend_line_length, my_settings.rsi_length) + 1
        if len(prices) < need:
            return ""

        price_now = prices[-1]

        # Rule 1: Trend is UP
        the_trend = chart_math.average(prices, my_settings.trend_line_length)
        if the_trend is None or price_now <= the_trend:
            return ""

        # Rule 2: RSI in healthy range
        rsi_now = chart_math.rsi_line(prices, my_settings.rsi_length)[-1]
        if rsi_now is None:
            return ""
        if not (my_settings.rsi_too_low < rsi_now < my_settings.rsi_too_high):
            return ""

        return "BUY"


MY_PLANS = {
    "trend_rsi_simple": MyPlan(),
    "trend_rsi_volume_bollinger": MyPlan(),  # keep old name as alias so nothing breaks
}


def pick_plan(name: str) -> MyPlan:
    if name not in MY_PLANS:
        return MY_PLANS["trend_rsi_simple"]
    return MY_PLANS[name]
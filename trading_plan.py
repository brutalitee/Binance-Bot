"""
trading_plan.py  - TEMPORARY DEBUG VERSION
------------------------------------------
Extremely loose entry rules so we can see the maximum possible trade count.
Use this ONLY for diagnosis, then we will put a real strategy back.
"""

from typing import Optional

import chart_math
import my_settings


class CoinPurchase:
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
        obj = cls(data["coin_name"], data["buy_price"], data["amount_of_coin"])
        obj.emergency_exit_price = data.get("emergency_exit_price", obj.emergency_exit_price)
        obj.dream_sell_price = data.get("dream_sell_price", obj.dream_sell_price)
        obj.highest_price_seen = data.get("highest_price_seen", data["buy_price"])
        return obj


class MyPlan:
    """DEBUG: Very loose entry rules."""

    plan_name = "debug_loose"

    def should_i_buy(self, candles: list) -> str:
        prices = [c["close"] for c in candles]

        # Need only a short history
        if len(prices) < 30:
            return ""

        price_now = prices[-1]

        # Extremely soft trend filter (20-period SMA)
        the_trend = chart_math.average(prices, 20)
        if the_trend is None:
            return ""

        # Buy if price is even slightly above the short SMA
        # (or remove this line completely if you want maximum trades)
        if price_now > the_trend * 0.995:   # almost always true
            return "BUY"

        return ""


MY_PLANS = {
    "debug_loose": MyPlan(),
    "trend_rsi_simple": MyPlan(),
}


def pick_plan(name: str) -> MyPlan:
    return MY_PLANS.get(name, MY_PLANS["debug_loose"])
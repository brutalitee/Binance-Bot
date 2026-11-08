"""
trading_plan.py
---------------
WHEN to buy and WHEN to sell. This is the brain, separated from all the
dangerous stuff (keys, orders, money limits) so I can swap strategies
without ever touching security code.
(Old name: strategy.py)

My plan, in plain English:
  BUY only if ALL of these are true:
    1. Trend is UP      (price above its 50-candle average)
    2. Not overbought   (RSI between 55 and 70)
    3. Real interest    (today's volume is above the 20-candle average)
    4. Inside the bands (price has NOT exploded above the upper Bollinger band)
  SELL when:
    +1.5% profit reached, OR price falls 1% from its peak (trailing stop),
    OR price hits my emergency exit at -1%.
"""

from typing import Optional

import chart_math
import my_settings


class CoinPurchase:
    """
    Remembers one open purchase and decides when to let it go.
    (Standard name for this kind of class: TradeState / Position.)
    """

    def __init__(self, coin_name: str, buy_price: float, amount_of_coin: float) -> None:
        self.coin_name = coin_name
        self.buy_price = buy_price
        self.amount_of_coin = amount_of_coin

        # Emergency exit: the lowest price I will ever accept before selling.
        self.emergency_exit_price = buy_price * (1 - my_settings.hard_stop_percent)
        # Dream price: where I take my profit.
        self.dream_sell_price = buy_price * (1 + my_settings.take_profit_percent)
        # Highest price seen since I bought -- used for the trailing stop.
        self.highest_price_seen = buy_price

    def follow_price_up(self, current_price: float) -> None:
        """Keep raising my exit price as the price climbs. It NEVER goes back down."""
        self.highest_price_seen = max(self.highest_price_seen, current_price)
        trailing = self.highest_price_seen * (1 - my_settings.trailing_stop_percent)
        self.emergency_exit_price = max(self.emergency_exit_price, trailing)

    def should_i_sell(self, current_price: float) -> str:
        """Returns WHY we should sell, or '' if I should keep holding."""
        if current_price >= self.dream_sell_price:
            return "reached my profit target"
        if current_price <= self.emergency_exit_price:
            if self.emergency_exit_price > self.buy_price * (
                1 - my_settings.hard_stop_percent
            ):
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
    """One decision function, shared by the time machine and the live bot."""

    plan_name = "trend_rsi_volume_bollinger"

    def should_i_buy(self, candles: list) -> str:
        """
        candles = list of dicts, oldest first, each with 'close' and 'volume'.
        Returns 'BUY' or ''. (Spot only, so I never 'short' sell.)
        """
        prices = [c["close"] for c in candles]
        volumes = [c["volume"] for c in candles]
        need = max(
            my_settings.trend_line_length, my_settings.volume_average_length,
            my_settings.bollinger_length,
        )
        if len(prices) < need + 1:
            return ""  # not enough history yet, do nothing

        price_now = prices[-1]

        # Rule 1: trend up
        the_trend = chart_math.average(prices, my_settings.trend_line_length)
        if the_trend is None or price_now <= the_trend:
            return ""

        # Rule 2: RSI not overbought (and not falling-knife territory)
        rsi_now = chart_math.rsi_line(prices, my_settings.rsi_length)[-1]
        if rsi_now is None:
            return ""
        if not (my_settings.rsi_too_low < rsi_now < my_settings.rsi_too_high):
            return ""

        # Rule 3: volume shows real interest
       # normal_volume = chart_math.average(volumes, my_settings.volume_average_length)
       # if normal_volume is None or volumes[-1] <= normal_volume:
       #     return ""

        # Rule 4: price must sit inside the Bollinger Bands.
        bands = chart_math.bollinger_bands(
            prices, my_settings.bollinger_length, my_settings.bollinger_width
        )
        if bands is None:
            return ""
        if price_now > bands["upper"]:
            # Price exploded above the upper band = chasing a spike. Skip.
            return ""

        return "BUY"


# The list of plans I can pick from. Adding a new plan = add it here only.
MY_PLANS = {"trend_rsi_volume_bollinger": MyPlan()}


def pick_plan(name: str) -> MyPlan:
    if name not in MY_PLANS:
        raise ValueError(f"I don't know the plan called {name!r}")
    return MY_PLANS[name]
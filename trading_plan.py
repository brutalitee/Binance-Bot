# trading_plan.py
"""
WHEN to buy and WHEN to sell.
This is the brain, separated from keys, orders and money limits.
"""

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
        self.stop_order_id: Optional[int] = None  # exchange-side stop if we placed one

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
            "stop_order_id": self.stop_order_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CoinPurchase":
        obj = cls(data["coin_name"], data["buy_price"], data["amount_of_coin"])
        obj.emergency_exit_price = data["emergency_exit_price"]
        obj.dream_sell_price = data["dream_sell_price"]
        obj.highest_price_seen = data["highest_price_seen"]
        obj.stop_order_id = data.get("stop_order_id")
        return obj


class MyPlan:
    plan_name = "trend_rsi_volume_bollinger"

    def should_i_buy(self, candles: list) -> str:
        prices = [c["close"] for c in candles]
        volumes = [c["volume"] for c in candles]
        need = max(
            my_settings.trend_line_length, my_settings.volume_average_length,
            my_settings.bollinger_length,
        )
        if len(prices) < need + 1:
            return ""

        price_now = prices[-1]

        the_trend = chart_math.average(prices, my_settings.trend_line_length)
        if the_trend is None or price_now <= the_trend:
            return ""

        rsi_now = chart_math.rsi_line(prices, my_settings.rsi_length)[-1]
        if rsi_now is None:
            return ""
        if not (my_settings.rsi_too_low < rsi_now < my_settings.rsi_too_high):
            return ""

        normal_volume = chart_math.average(volumes, my_settings.volume_average_length)
        if normal_volume is None or volumes[-1] <= normal_volume:
            return ""

        bands = chart_math.bollinger_bands(
            prices, my_settings.bollinger_length, my_settings.bollinger_width
        )
        if bands is None:
            return ""
        if price_now > bands["upper"]:
            return ""

        return "BUY"


MY_PLANS = {"trend_rsi_volume_bollinger": MyPlan()}


def pick_plan(name: str) -> MyPlan:
    if name not in MY_PLANS:
        raise ValueError(f"I don't know the plan called {name!r}")
    return MY_PLANS[name]
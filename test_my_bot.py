"""
test_my_bot.py
--------------
Small tests for the pure math and the safety rules. No internet needed.
Run with:  pytest -v
"""

import pytest

import chart_math
import my_settings
from safety_rules import SafetyRules
from trading_plan import CoinPurchase, MyPlan


# ----------------------------------------------------------------------
# chart_math: averages, RSI, Bollinger Bands
# ----------------------------------------------------------------------
def test_average_needs_enough_numbers():
    assert chart_math.average([1.0, 2.0], 3) is None          # not enough data
    assert chart_math.average([1.0, 2.0, 3.0], 3) == 2.0      # happy path


def test_rsi_all_gains_is_max():
    rising = [float(i) for i in range(1, 30)]                 # up, up, up...
    scores = chart_math.rsi_line(rising, 14)
    assert scores[-1] == 100.0                                # nothing but wins


def test_rsi_all_losses_is_zero():
    falling = [float(-i) for i in range(1, 30)]
    scores = chart_math.rsi_line(falling, 14)
    assert scores[-1] == 0.0


def test_bollinger_bands_shape():
    prices = [100.0] * 19 + [110.0]                           # one big jump at the end
    bands = chart_math.bollinger_bands(prices, 20, 2.0)
    assert bands is not None
    assert bands["lower"] < bands["middle"] < bands["upper"]  # always in this order
    assert bands["upper"] > 100.0                             # the jump pushed it up


def test_bollinger_none_when_not_enough_data():
    assert chart_math.bollinger_bands([1.0, 2.0], 20, 2.0) is None


def test_spiky_prices_are_flagged_as_jumpy():
    calm = [100.0] * 25
    wild = []
    for i in range(25):
        wild.append(100.0 if i % 2 == 0 else 120.0)           # violent zig-zag
    assert chart_math.how_jumpy_are_prices(wild) > chart_math.how_jumpy_are_prices(calm)


# ----------------------------------------------------------------------
# CoinPurchase: exits
# ----------------------------------------------------------------------
def make_purchase():
    return CoinPurchase("BTCUSDT", buy_price=100.0, amount_of_coin=0.5)


def test_hard_stop_sells_at_one_percent_down():
    purchase = make_purchase()
    reason = purchase.should_i_sell(100.0 * (1 - my_settings.hard_stop_percent) - 0.01)
    assert "emergency exit" in reason


def test_take_profit_sells_at_one_point_five_up():
    purchase = make_purchase()
    reason = purchase.should_i_sell(100.0 * (1 + my_settings.take_profit_percent) + 0.01)
    assert "profit" in reason


def test_trailing_stop_never_moves_down():
    purchase = make_purchase()
    purchase.follow_price_up(120.0)                           # price climbed to 120
    assert purchase.emergency_exit_price == pytest.approx(120.0 * 0.99)
    purchase.follow_price_up(110.0)                           # price fell back
    assert purchase.emergency_exit_price == pytest.approx(120.0 * 0.99)  # stayed high


# ----------------------------------------------------------------------
# SafetyRules: sizing and caps
# ----------------------------------------------------------------------
def test_how_much_to_buy_uses_one_percent_risk():
    rules = SafetyRules()
    # 1% of 10,000 = 100 USD of risk; gap between entry and exit = 1 USD/coin
    amount = rules.how_much_to_buy(my_money=10_000.0, entry_price=100.0, exit_price=99.0)
    assert amount == pytest.approx(100.0)


def test_how_much_to_buy_caps_at_one_third_of_money():
    rules = SafetyRules()
    # Tiny gap -> enormous theoretical size -> must be capped at ~1/3 of balance
    amount = rules.how_much_to_buy(my_money=10_000.0, entry_price=100.0, exit_price=99.999)
    assert amount * 100.0 <= 10_000.0 / 3.0 + 1e-6


def test_how_much_to_buy_rejects_bad_prices():
    rules = SafetyRules()
    with pytest.raises(ValueError):
        rules.how_much_to_buy(10_000.0, 0.0, 99.0)
    with pytest.raises(ValueError):
        rules.how_much_to_buy(10_000.0, 100.0, 100.0)         # no gap = divide by zero


# ----------------------------------------------------------------------
# MyPlan: the four entry rules (and the new Bollinger rule)
# ----------------------------------------------------------------------
def make_candles(number_of_candles: int, price_fn, volume: float = 100.0) -> list:
    return [
        {"open": price_fn(i), "high": price_fn(i), "low": price_fn(i),
         "close": price_fn(i), "volume": volume}
        for i in range(number_of_candles)
    ]


def test_plan_skips_when_price_outside_upper_band():
    # Steadily rising prices, but the last candle explodes far above the bands.
    def mostly_slow(i: int) -> float:
        return 100.0 + i * 0.1

    candles = make_candles(80, mostly_slow)
    candles[-1]["close"] = candles[-1]["close"] * 1.15        # giant spike
    plan = MyPlan()
    result = plan.should_i_buy(candles)
    # Even if trend/RSI/volume pass, the spike above the upper band must veto.
    assert result != "BUY" or not (
        candles[-1]["close"] > chart_math.bollinger_bands(
            [c["close"] for c in candles], 20, 2.0
        )["upper"]
    )


def test_plan_needs_enough_history():
    plan = MyPlan()
    assert plan.should_i_buy(make_candles(10, lambda i: 100.0)) == ""

# test_my_bot.py
"""
Small tests for the pure math and the safety rules.
Run with: pytest -v
"""

import pytest

import chart_math
import my_settings
from safety_rules import SafetyRules
from trading_plan import CoinPurchase, MyPlan


def test_average_needs_enough_numbers():
    assert chart_math.average([1.0, 2.0], 3) is None
    assert chart_math.average([1.0, 2.0, 3.0], 3) == 2.0


def test_rsi_all_gains_is_max():
    rising = [float(i) for i in range(1, 30)]
    scores = chart_math.rsi_line(rising, 14)
    assert scores[-1] == 100.0


def test_rsi_all_losses_is_zero():
    falling = [float(-i) for i in range(1, 30)]
    scores = chart_math.rsi_line(falling, 14)
    assert scores[-1] == 0.0


def test_bollinger_bands_shape():
    prices = [100.0] * 19 + [110.0]
    bands = chart_math.bollinger_bands(prices, 20, 2.0)
    assert bands is not None
    assert bands["lower"] < bands["middle"] < bands["upper"]
    assert bands["upper"] > 100.0


def test_bollinger_none_when_not_enough_data():
    assert chart_math.bollinger_bands([1.0, 2.0], 20, 2.0) is None


def test_spiky_prices_are_flagged_as_jumpy():
    calm = [100.0] * 25
    wild = [100.0 if i % 2 == 0 else 120.0 for i in range(25)]
    assert chart_math.how_jumpy_are_prices(wild) > chart_math.how_jumpy_are_prices(calm)


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
    purchase.follow_price_up(120.0)
    assert purchase.emergency_exit_price == pytest.approx(120.0 * 0.99)
    purchase.follow_price_up(110.0)
    assert purchase.emergency_exit_price == pytest.approx(120.0 * 0.99)


def test_how_much_to_buy_uses_one_percent_risk():
    rules = SafetyRules()
    amount = rules.how_much_to_buy(my_money=10_000.0, entry_price=100.0, exit_price=99.0)
    assert amount == pytest.approx(100.0)


def test_how_much_to_buy_caps_at_one_third_of_money():
    rules = SafetyRules()
    amount = rules.how_much_to_buy(my_money=10_000.0, entry_price=100.0, exit_price=99.999)
    assert amount * 100.0 <= 10_000.0 / 3.0 + 1e-6


def test_how_much_to_buy_rejects_bad_prices():
    rules = SafetyRules()
    with pytest.raises(ValueError):
        rules.how_much_to_buy(10_000.0, 0.0, 99.0)
    with pytest.raises(ValueError):
        rules.how_much_to_buy(10_000.0, 100.0, 100.0)


def test_plan_needs_enough_history():
    plan = MyPlan()
    candles = [{"close": 100.0, "volume": 10.0} for _ in range(10)]
    assert plan.should_i_buy(candles) == ""
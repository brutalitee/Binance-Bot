"""
time_machine.py
---------------
Replays two years of old candles through the EXACT same plan and safety
rules the live bot uses, then shows me the report card.
(Old name: backtester.py)

Report card includes: win rate, profit factor, biggest losing dip, the
Sharpe score, and an honest "am I fooling myself?" warning.

Gate: only a passing report card lets me move up to paper trading.
"""

import json
import logging
import statistics
import time as time_module
from typing import Dict, List, Optional

import my_settings
from safety_rules import SafetyRules
from trading_plan import CoinPurchase, MyPlan

log = logging.getLogger("bot.time_machine")


class ReportCard:
    """The result of one replay. All the numbers I care about."""

    def __init__(self, coin_name: str, **numbers: float) -> None:
        self.coin_name = coin_name
        for key, value in numbers.items():
            setattr(self, key, value)

    def as_dict(self) -> dict:
        out = {"coin": self.coin_name}
        out.update({k: v for k, v in self.__dict__.items() if k != "coin_name"})
        return out


def download_two_years_of_candles(exchange) -> Dict[str, List[dict]]:
    """
    Walks backwards page by page (1000 candles at a time) until it has
    BACKTEST_YEARS of history for each of my coins. Sleeps between pages
    so the exchange never gets annoyed.
    """
    history: Dict[str, List[dict]] = {}
    years_of_milliseconds = my_settings.backtest_years * 365 * 24 * 3600 * 1000

    for coin_name in my_settings.my_coins:
        all_candles: List[dict] = []
        older_than: Optional[int] = None

        while True:
            page = exchange.get_old_candles_page(coin_name, older_than)
            if not page:
                break
            for one in page:
                all_candles.append({
                    "open_time": one[0],
                    "open": float(one[1]),
                    "high": float(one[2]),
                    "low": float(one[3]),
                    "close": float(one[4]),
                    "volume": float(one[5]),
                })
            earliest = page[0][0]
            if older_than == earliest - 1 or len(page) < 1000:
                break  # reached the beginning of what we need
            older_than = earliest - 1
            time_module.sleep(my_settings.wait_between_calls)

        all_candles.sort(key=lambda c: c["open_time"])
        cutoff = all_candles[-1]["open_time"] - years_of_milliseconds
        history[coin_name] = [c for c in all_candles if c["open_time"] >= cutoff]
        log.info("Collected %d candles for %s.", len(history[coin_name]), coin_name)
    return history


def replay_history(coin_name: str, candles: List[dict],
                   starting_money: float) -> ReportCard:
    """
    The heart of it: pretend to trade, one candle at a time, using the
    same MyPlan.should_i_buy and CoinPurchase as the live bot.
    """
    plan = MyPlan()
    rules = SafetyRules()
    my_money = starting_money
    my_money_over_time: List[float] = []
    winning_trades: List[float] = []
    losing_trades: List[float] = []
    all_trade_results: List[float] = []
    open_purchase: Optional[CoinPurchase] = None
    money_at_start_of_day = starting_money
    yesterday_marker: int = -1

    warmup = max(my_settings.trend_line_length, my_settings.volume_average_length,
                 my_settings.bollinger_length)

    for i in range(warmup, len(candles)):
        candle = candles[i]
        price_now = candle["close"]

        # New day? Remember how much money I woke up with.
        day_number = candle["open_time"] // 86_400_000
        if day_number != yesterday_marker:
            yesterday_marker = day_number
            money_at_start_of_day = my_money

        # --- first: take care of a purchase I already hold ---
        if open_purchase is not None:
            open_purchase.follow_price_up(price_now)
            reason = open_purchase.should_i_sell(price_now)
            if reason:
                sell_price = price_now * (1 - my_settings.slippage_percent)
                price_change = (sell_price - open_purchase.buy_price) / open_purchase.buy_price
                real_result = price_change - my_settings.fee_percent * 2  # fees both ways
                # My 1%-risk rule: a full -1% emergency exit costs exactly 1% of my money.
                money_change = (my_money * my_settings.risk_one_percent
                                / my_settings.hard_stop_percent) * real_result
                my_money += money_change
                if real_result > 0:
                    winning_trades.append(real_result)
                    rules.i_won()
                else:
                    losing_trades.append(abs(real_result))
                    rules.i_lost()
                all_trade_results.append(real_result)
                open_purchase = None

        # --- then: maybe buy something new ---
        if open_purchase is None:
            try:
                rules.check_todays_damage(money_at_start_of_day, my_money)
            except RuntimeError:
                my_money_over_time.append(my_money)
                continue  # paused today, just watch
            if rules.losses_in_a_row >= 3:
                my_money_over_time.append(my_money)
                continue
            calm_enough, _ = rules.is_the_market_calm_enough(
                [c["close"] for c in candles[max(0, i - 21): i + 1]]
            )
            if not calm_enough:
                my_money_over_time.append(my_money)
                continue
            if plan.should_i_buy(candles[: i + 1]) == "BUY":
                buy_price = price_now * (1 + my_settings.slippage_percent)
                exit_price = buy_price * (1 - my_settings.hard_stop_percent)
                try:
                    amount = rules.how_much_to_buy(my_money, buy_price, exit_price)
                except ValueError:
                    my_money_over_time.append(my_money)
                    continue
                open_purchase = CoinPurchase(coin_name, buy_price, amount)

        my_money_over_time.append(my_money)

    # ---------------- the report card ----------------
    total = len(winning_trades) + len(losing_trades)
    win_rate = len(winning_trades) / total if total else 0.0
    total_won = sum(winning_trades)
    total_lost = sum(losing_trades)
    if total_lost > 0:
        profit_factor = total_won / total_lost
    elif total_won > 0:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    # Biggest losing dip: the deepest drop from a money-high to what came after.
    peak = my_money
    biggest_dip = 0.0
    for money_point in my_money_over_time:
        peak = max(peak, money_point)
        dip = (peak - money_point) / peak
        biggest_dip = max(biggest_dip, dip)

    # Sharpe: are my wins smooth and steady, or luck and chaos?
    sharpe = 0.0
    if len(all_trade_results) > 1 and statistics.stdev(all_trade_results) > 0:
        sharpe = (statistics.mean(all_trade_results)
                  / statistics.stdev(all_trade_results)) * (len(all_trade_results) ** 0.5)

    # --- honesty checks ---
    worries: List[str] = []
    if win_rate > my_settings.too_good_win_rate:
        worries.append(
            f"Winning {win_rate:.0%} of the time looks TOO good "
            f"(over {my_settings.too_good_win_rate:.0%}). I probably tricked myself."
        )
    if total < 30:
        worries.append(f"Only {total} trades -- too few to trust.")

    passed = (
        profit_factor > my_settings.good_profit_factor
        and biggest_dip < my_settings.safe_max_drawdown
        and not worries
    )

    card = ReportCard(
        coin_name,
        trades_total=total,
        trades_won=len(winning_trades),
        trades_lost=len(losing_trades),
        win_rate=win_rate,
        profit_factor=profit_factor,
        biggest_loss_dip=biggest_dip,
        sharpe_score=sharpe,
        average_win=total_won / len(winning_trades) if winning_trades else 0.0,
        average_loss=total_lost / len(losing_trades) if losing_trades else 0.0,
        money_at_end=my_money,
        money_at_start=starting_money,
        passed_the_gate=passed,
        worries=" ".join(worries) if worries else "",
    )
    log.info("REPORT CARD %s: %s", coin_name, json.dumps(card.as_dict()))
    return card

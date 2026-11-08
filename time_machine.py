"""
time_machine.py
---------------
Replays historical candles through the exact same plan and safety rules.
Uses data-api.binance.vision to avoid geo-blocking (HTTP 451).
"""

import json
import logging
import statistics
import time as time_module
from datetime import datetime, timezone
from typing import Dict, List, Optional

import my_settings
from safety_rules import SafetyRules
from trading_plan import CoinPurchase, MyPlan

log = logging.getLogger("bot.time_machine")


class ReportCard:
    def __init__(self, coin_name: str, **numbers: float) -> None:
        self.coin_name = coin_name
        for key, value in numbers.items():
            setattr(self, key, value)

    def as_dict(self) -> dict:
        out = {"coin": self.coin_name}
        out.update({k: v for k, v in self.__dict__.items() if k != "coin_name"})
        return out


def save_backtest_result(card: ReportCard) -> None:
    history_file = my_settings.backtest_history_file
    history = []
    if history_file.exists():
        try:
            with history_file.open("r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []

    entry = {
        "time": datetime.now(timezone.utc).isoformat(),
        "coin": card.coin_name,
        "trades": card.trades_total,
        "win_rate": round(card.win_rate, 3),
        "profit_factor": round(card.profit_factor, 3) if card.profit_factor != float("inf") else 999.0,
        "max_dd": round(card.biggest_loss_dip, 3),
        "final_money": round(card.money_at_end, 2),
        "passed": card.passed_the_gate,
        "settings": {
            "rsi_low": my_settings.rsi_too_low,
            "rsi_high": my_settings.rsi_too_high,
            "trend": my_settings.trend_line_length,
            "vol_len": my_settings.volume_average_length,
            "bb_width": my_settings.bollinger_width,
            "tp": my_settings.take_profit_percent,
            "sl": my_settings.hard_stop_percent,
        },
    }
    history.append(entry)

    with history_file.open("w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


def download_two_years_of_candles(exchange) -> Dict[str, List[dict]]:
    history: Dict[str, List[dict]] = {}
    one_hour_ms = 3_600_000
    years_of_ms = my_settings.backtest_years * 365 * 24 * one_hour_ms

    real_address = "https://data-api.binance.vision"
    original_address = exchange.address
    exchange.address = real_address

    try:
        for coin_name in my_settings.my_coins:
            all_candles: List[dict] = []
            fetch_from = int(time_module.time() * 1000) - years_of_ms

            while True:
                page = exchange.public_call(
                    "GET", "/api/v3/klines",
                    {
                        "symbol": coin_name,
                        "interval": my_settings.candle_size,
                        "limit": 1000,
                        "startTime": fetch_from,
                    },
                )
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

                log.info("    %s: %d candles collected so far...",
                         coin_name, len(all_candles))

                newest_open_time = page[-1][0]
                next_start = newest_open_time + one_hour_ms

                if next_start <= fetch_from:
                    log.warning("Download for %s stalled; stopping this coin.", coin_name)
                    break

                fetch_from = next_start
                time_module.sleep(my_settings.wait_between_calls)

                if newest_open_time + one_hour_ms >= time_module.time() * 1000:
                    break

            unique: Dict[int, dict] = {c["open_time"]: c for c in all_candles}
            ordered = [unique[k] for k in sorted(unique)]
            history[coin_name] = ordered
            log.info("Collected %d candles for %s (about %.1f months).",
                     len(ordered), coin_name, len(ordered) / (24 * 30.4))
    finally:
        exchange.address = original_address

    return history


def replay_history(coin_name: str, candles: List[dict],
                   starting_money: float) -> ReportCard:
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

        day_number = candle["open_time"] // 86_400_000
        if day_number != yesterday_marker:
            yesterday_marker = day_number
            money_at_start_of_day = my_money

        if open_purchase is not None:
            open_purchase.follow_price_up(price_now)
            reason = open_purchase.should_i_sell(price_now)
            if reason:
                sell_price = price_now * (1 - my_settings.slippage_percent)
                price_change = (sell_price - open_purchase.buy_price) / open_purchase.buy_price
                real_result = price_change - my_settings.fee_percent * 2
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

        if open_purchase is None:
            try:
                rules.check_todays_damage(money_at_start_of_day, my_money)
            except RuntimeError:
                my_money_over_time.append(my_money)
                continue
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

    peak = my_money
    biggest_dip = 0.0
    for money_point in my_money_over_time:
        peak = max(peak, money_point)
        dip = (peak - money_point) / peak
        biggest_dip = max(biggest_dip, dip)

    sharpe = 0.0
    if len(all_trade_results) > 1 and statistics.stdev(all_trade_results) > 0:
        sharpe = (statistics.mean(all_trade_results)
                  / statistics.stdev(all_trade_results)) * (len(all_trade_results) ** 0.5)

    worries: List[str] = []
    if win_rate > my_settings.too_good_win_rate:
        worries.append(
            f"Winning {win_rate:.0%} of the time looks TOO good "
            f"(over {my_settings.too_good_win_rate:.0%}). I probably tricked myself."
        )
    if total < my_settings.min_trades_required:
        worries.append(
            f"Only {total} trades -- too few to trust "
            f"(need at least {my_settings.min_trades_required})."
        )

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
    save_backtest_result(card)
    return card
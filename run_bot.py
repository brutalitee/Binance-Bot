"""
run_bot.py
----------
The on/off switch of the whole operation. (Old name: main.py)

What it does:
  BACKTEST -> replay history, write the report card, decide if PAPER is earned
  PAPER    -> live prices, fake money, keeps a diary of winning days
  LIVE     -> real money, BLOCKED unless the diary proves 30 winning days
              AND the backtest passed AND I typed LIVE_CONFIRMED=YES

Nothing in here touches my secret keys directly; that only happens inside
talk_to_binance.py.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import my_settings
from safety_rules import SafetyRules
from talk_to_binance import BinanceConnection, SafetyShutdown
from time_machine import download_two_years_of_candles, replay_history
from trading_plan import CoinPurchase, MyPlan, pick_plan


# ----------------------------------------------------------------------
# Logging: everything the bot does gets written to bot.log AND shown to me.
# If a secret ever sneaks into a log line, the filter blacks it out.
# ----------------------------------------------------------------------
class HideSecrets(logging.Filter):
    def __init__(self) -> None:
        super().__init__()
        self.secrets = [s for s in (my_settings.api_key, my_settings.api_secret) if s]

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        for secret in self.secrets:
            if secret and secret in message:
                record.msg = message.replace(secret, "***hidden***")
                record.args = None
        return True


def set_up_logging() -> None:
    tell_terminal = logging.StreamHandler(sys.stdout)
    save_to_file = logging.FileHandler(my_settings.log_file)
    tell_terminal.addFilter(HideSecrets())
    save_to_file.addFilter(HideSecrets())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[save_to_file, tell_terminal],
    )


# ----------------------------------------------------------------------
# The paper-trading diary: proof that I deserve real money (or don't)
# ----------------------------------------------------------------------
def read_diary() -> dict:
    if my_settings.paper_results_file.exists():
        with my_settings.paper_results_file.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    return {"winning_days": 0, "days_recorded": 0, "daily_results": {},
            "backtest_passed": False}


def write_diary(diary: dict) -> None:
    with my_settings.paper_results_file.open("w", encoding="utf-8") as fh:
        json.dump(diary, fh, indent=2)


def save_open_positions(purchases: Dict[str, CoinPurchase]) -> None:
    data = {k: v.to_dict() for k, v in purchases.items()}
    with my_settings.open_positions_file.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def load_open_positions() -> Dict[str, CoinPurchase]:
    if not my_settings.open_positions_file.exists():
        return {}
    with my_settings.open_positions_file.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return {k: CoinPurchase.from_dict(v) for k, v in data.items()}


# ----------------------------------------------------------------------
# The last door before real money
# ----------------------------------------------------------------------
def check_if_real_money_is_allowed(diary: dict) -> None:
    reasons_to_stop = []
    if not diary.get("backtest_passed"):
        reasons_to_stop.append("the time machine never gave me a passing report card")
    if diary.get("winning_days", 0) < my_settings.paper_days_needed:
        reasons_to_stop.append(
            f"I only have {diary.get('winning_days', 0)} winning paper days, "
            f"but I need {my_settings.paper_days_needed}"
        )
    if my_settings.use_testnet:
        reasons_to_stop.append("I'm still pointing at the practice server (USE_TESTNET)")
    if os.getenv("LIVE_CONFIRMED", "").strip().upper() != "YES":
        reasons_to_stop.append("LIVE_CONFIRMED is not set to YES in .env")

    if reasons_to_stop:
        logging.getLogger("bot.runner").error(
            "REAL MONEY IS LOCKED. Reasons: %s", "; ".join(reasons_to_stop)
        )
        sys.exit(1)
    logging.getLogger("bot.runner").warning(
        "*** REAL MONEY MODE *** Remember: only money I can afford to lose."
    )


# ----------------------------------------------------------------------
# The engine: buys, sells, remembers, obeys the safety rules
# ----------------------------------------------------------------------
class RobotTrader:
    def __init__(self, exchange: Optional[BinanceConnection], mode: str,
                 my_money: float) -> None:
        self.exchange = exchange
        self.mode = mode
        self.my_money = my_money               # paper = fake dollars; live = real
        self.plan: MyPlan = pick_plan("debug_loose")
        self.rules = SafetyRules()
        self.my_purchases: Dict[str, CoinPurchase] = load_open_positions()
        self.money_at_start_of_day = my_money
        self.today_marker: int = -1
        if self.my_purchases:
            logging.getLogger("bot.robot").info(
                "Loaded %d open position(s) from disk.", len(self.my_purchases)
            )

    def wake_up_new_day(self) -> None:
        today = datetime.now(timezone.utc).toordinal()
        if today != self.today_marker:
            self.today_marker = today
            self.money_at_start_of_day = self.my_money

    def fake_fill(self, coin_name: str, side: str, amount: float, price: float) -> None:
        """PAPER mode: pretend the order worked, subtract the fee honestly."""
        fee = amount * price * my_settings.fee_percent
        self.my_money -= fee
        logging.getLogger("bot.robot").info(
            "PAPER %s %s amount=%.6f price=%.2f fee=%.4f money_left=%.2f",
            side, coin_name, amount, price, fee, self.my_money,
        )

    def really_fill(self, coin_name: str, side: str, amount: float, price: float) -> None:
        """LIVE mode: real order through the guarded connection."""
        assert self.exchange is not None
        self.exchange.place_market_order(coin_name, side, amount, price)

    def send_order(self, coin_name: str, side: str, amount: float, price: float) -> None:
        if self.mode == "PAPER":
            self.fake_fill(coin_name, side, amount, price)
        else:
            self.really_fill(coin_name, side, amount, price)

    def one_round(self) -> None:
        self.wake_up_new_day()
        try:
            self.rules.check_todays_damage(self.money_at_start_of_day, self.my_money)
        except RuntimeError:
            return  # resting after a rough day

        assert self.exchange is not None
        for coin_name in my_settings.my_coins:
            candles = self.exchange.get_candles(coin_name, how_many=120)
            if len(candles) < 60:
                continue  # not enough history right now
            price_now = candles[-1]["close"]

            # --- look after what I already hold ---
            held = self.my_purchases.get(coin_name)
            if held is not None:
                held.follow_price_up(price_now)
                reason = held.should_i_sell(price_now)
                if reason:
                    sell_price = price_now * (1 - my_settings.slippage_percent)
                    self.send_order(coin_name, "SELL", held.amount_of_coin, sell_price)
                    price_change = (sell_price - held.buy_price) / held.buy_price
                    real_result = price_change - my_settings.fee_percent * 2
                    money_change = (self.money_at_start_of_day
                                    * my_settings.risk_one_percent
                                    / my_settings.hard_stop_percent) * real_result
                    self.my_money += money_change
                    if real_result > 0:
                        self.rules.i_won()
                    else:
                        self.rules.i_lost()
                    logging.getLogger("bot.robot").info(
                        "SOLD %s because: %s. Result: %.2f%% (%.2f USD)",
                        coin_name, reason, real_result * 100, money_change,
                    )
                    del self.my_purchases[coin_name]
                    save_open_positions(self.my_purchases)
                continue

            # --- maybe buy something new ---
            if not self.rules.am_i_allowed_to_trade(self.my_purchases):
                continue
            now_hour = datetime.now(timezone.utc).hour
            if not self.rules.is_it_a_quiet_news_hour(now_hour):
                continue
            calm_enough, jumpy = self.rules.is_the_market_calm_enough(
                [c["close"] for c in candles]
            )
            if not calm_enough:
                logging.getLogger("bot.robot").info(
                    "Too jumpy (%.2f%%) -- watching %s instead of buying.", jumpy, coin_name
                )
                continue
            if self.plan.should_i_buy(candles) == "BUY":
                buy_price = price_now * (1 + my_settings.slippage_percent)
                exit_price = buy_price * (1 - my_settings.hard_stop_percent)
                try:
                    amount = self.rules.how_much_to_buy(self.my_money, buy_price, exit_price)
                except ValueError as mistake:
                    logging.getLogger("bot.robot").warning(
                        "Skipped %s: %s", coin_name, mistake
                    )
                    continue
                self.send_order(coin_name, "BUY", amount, buy_price)
                self.my_purchases[coin_name] = CoinPurchase(coin_name, buy_price, amount)
                save_open_positions(self.my_purchases)
                logging.getLogger("bot.robot").info(
                    "BOUGHT %s amount=%.6f at %.2f, emergency exit at %.2f",
                    coin_name, amount, buy_price, exit_price,
                )


# ----------------------------------------------------------------------
# Starting point
# ----------------------------------------------------------------------
def run_backtest_mode() -> None:
    log = logging.getLogger("bot.runner")
    log.info("Replaying history. No money involved, this is homework.")

    # Force the unrestricted public market-data endpoint
    # (api.binance.com returns 451 in many countries; Testnet has almost no history)
    real_address = "https://data-api.binance.vision"
    exchange = BinanceConnection("", "", real_address, is_testnet=True)

    history = download_two_years_of_candles(exchange)

    everything_passed = True
    for coin_name in my_settings.my_coins:
        card = replay_history(coin_name, history[coin_name], starting_money=10_000.0)
        if not card.passed_the_gate:
            everything_passed = False
        if card.worries:
            log.warning("HONESTY WARNING [%s]: %s", coin_name, card.worries)

    diary = read_diary()
    diary["backtest_passed"] = everything_passed
    write_diary(diary)
    log.info("Backtest done. Earned the right to paper trade: %s", everything_passed)
    if everything_passed:
        log.info("Next step: set TRADING_MODE=PAPER in .env and let it run 30 days.")
    else:
        log.info("The plan didn't prove itself. Rework the plan -- don't paper trade a weak plan.")


def main() -> None:
    set_up_logging()
    log = logging.getLogger("bot.runner")

    if my_settings.stop_everything:
        log.critical("Big red button is ON. Nothing will trade. Goodbye.")
        sys.exit(1)

    log.info("Mode=%s testnet=%s coins=%s",
             my_settings.trading_mode, my_settings.use_testnet, my_settings.my_coins)

    if my_settings.trading_mode == "BACKTEST":
        run_backtest_mode()
        return

    exchange = BinanceConnection(
        my_settings.api_key, my_settings.api_secret,
        my_settings.api_address, my_settings.use_testnet,
    )

    if my_settings.trading_mode == "LIVE":
        check_if_real_money_is_allowed(read_diary())

    # PAPER starts with pretend $10,000; LIVE counts my actual US dollars.
    my_money = 10_000.0
    if my_settings.trading_mode == "LIVE":
        account = exchange.signed_call("GET", "/api/v3/account", {})
        for purse in account.get("balances", []):
            if purse["asset"] == "USDT":
                my_money = float(purse["free"])
        log.info("Real money detected: %.2f USDT", my_money)

    robot = RobotTrader(exchange, my_settings.trading_mode, my_money)
    log.info("Robot is awake. Press Ctrl+C to tuck it in.")

    today_label = datetime.now(timezone.utc).date().isoformat()
    try:
        while True:
            # IMPORTANT (bug fix): write yesterday's diary entry BEFORE the
            # robot wakes up into the new day, because waking up resets the
            # 'money at start of day' baseline. Recording afterwards would
            # have measured nonsense.
            if my_settings.trading_mode == "PAPER":
                today = datetime.now(timezone.utc).date().isoformat()
                if today != today_label:
                    diary = read_diary()
                    day_result = robot.my_money - robot.money_at_start_of_day
                    daily = diary.setdefault("daily_results", {})
                    if today not in daily:  # count each day exactly once
                        daily[today] = round(day_result, 2)
                        diary["days_recorded"] = diary.get("days_recorded", 0) + 1
                        if day_result > 0:
                            diary["winning_days"] = diary.get("winning_days", 0) + 1
                        write_diary(diary)
                        log.info("Diary: %s result %.2f USD (winning days: %d)",
                                 today, day_result, diary["winning_days"])
                    today_label = today

            robot.one_round()
            time.sleep(60)  # one-minute heartbeat; 1h candles don't need faster
    except KeyboardInterrupt:
        log.info("You stopped the bot with Ctrl-C. Open positions saved.")
        save_open_positions(robot.my_purchases)
    except SafetyShutdown as e:
        log.critical("Safety shutdown: %s", e)
        save_open_positions(robot.my_purchases)
        sys.exit(1)


if __name__ == "__main__":
    main()
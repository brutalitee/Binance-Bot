# safety_rules.py
"""
The guardian. Nothing buys anything unless this file agrees.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import chart_math
import my_settings

log = logging.getLogger("bot.safety")


class SafetyRules:
    def __init__(self) -> None:
        self.losses_in_a_row: int = 0
        self.pause_until: Optional[datetime] = None

    def am_i_allowed_to_trade(self, my_open_purchases: dict) -> bool:
        if my_settings.stop_everything:
            log.warning("Big red button is ON. No trading.")
            return False
        if self.pause_until and datetime.now(timezone.utc) < self.pause_until:
            return False
        if len(my_open_purchases) >= my_settings.max_trades_at_once:
            return False
        return True

    def check_todays_damage(self, money_at_start_of_day: float, my_money: float) -> None:
        if money_at_start_of_day <= 0:
            return
        todays_result = (my_money - money_at_start_of_day) / money_at_start_of_day
        if todays_result <= -my_settings.daily_loss_limit:
            already_paused = (
                self.pause_until is not None
                and datetime.now(timezone.utc) < self.pause_until
            )
            if not already_paused:
                self.pause_until = datetime.now(timezone.utc) + timedelta(
                    hours=my_settings.daily_pause_hours
                )
                log.critical(
                    "Ouch: I lost %.1f%% today. Pausing all trading for %d hours.",
                    abs(todays_result) * 100,
                    my_settings.daily_pause_hours,
                )
            raise RuntimeError("Paused: too much damage today.")

    def how_much_to_buy(self, my_money: float, entry_price: float, exit_price: float) -> float:
        money_i_can_lose = my_money * my_settings.risk_one_percent
        gap = abs(entry_price - exit_price)
        if entry_price <= 0 or exit_price <= 0 or gap <= 0:
            raise ValueError("Prices must be positive and exit must differ from entry.")

        coins = money_i_can_lose / gap
        order_value = coins * entry_price

        if order_value < my_settings.smallest_order_usd:
            raise ValueError(
                f"Order worth {order_value:.2f} USD is smaller than the "
                f"{my_settings.smallest_order_usd:.0f} USD floor."
            )

        biggest_single_bet = my_money / 3.0
        if order_value > biggest_single_bet:
            coins = biggest_single_bet / entry_price
            log.warning("Shrunk the order: I never bet more than 1/3 of my money on one coin.")
        return coins

    def i_lost(self) -> None:
        self.losses_in_a_row += 1
        if self.losses_in_a_row >= 3:
            self.pause_until = datetime.now(timezone.utc) + timedelta(
                hours=my_settings.loss_streak_pause_hours
            )
            log.critical("3 losses in a row. Resting for %d hours.",
                         my_settings.loss_streak_pause_hours)

    def i_won(self) -> None:
        self.losses_in_a_row = 0

    def is_the_market_calm_enough(self, closing_prices: List[float]) -> Tuple[bool, float]:
        jumpy = chart_math.how_jumpy_are_prices(closing_prices, look_back=20)
        if jumpy > my_settings.too_crazy_volatility:
            return False, jumpy
        return True, jumpy

    def is_it_a_quiet_news_hour(self, current_utc_hour: int) -> bool:
        return current_utc_hour not in my_settings.quiet_news_hours_utc
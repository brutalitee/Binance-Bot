"""
talk_to_binance.py
------------------
The only file that speaks to Binance. Keeping it alone means all the
dangerous parts (my keys, signing, ordering) live in ONE place I can
double-check. (Old name: binance_client.py)

Safety tricks used here:
  - My keys come from .env only. They are never printed or saved anywhere.
  - On start (real money mode) I ASK Binance what my key may do. If it can
    withdraw coins, I shut everything down immediately. Fail closed.
  - Every order is checked for silly mistakes BEFORE it is sent.
  - If the exchange says "slow down" (HTTP 429), I sleep and retry kindly,
    with growing waits. If it bans my IP (418), I stop dead -- no hammering.
"""

import hashlib
import hmac
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests

import my_settings

log = logging.getLogger("bot.exchange")


class ExchangeProblem(Exception):
    """Something went wrong talking to Binance."""


class SafetyShutdown(Exception):
    """Something unsafe happened and I must stop NOW (like withdrawals enabled)."""


class BinanceConnection:
    def __init__(self, my_key: str, my_secret: str, address: str, is_testnet: bool) -> None:
        self.my_key = my_key
        self.my_secret = my_secret.encode()  # HMAC needs bytes
        self.address = address.rstrip("/")
        self.web = requests.Session()
        self.web.headers.update({"X-MBX-APIKEY": my_key})

        self.coin_rules: Dict[str, dict] = {}
        self.known_orders: Dict[str, set] = {}   # remember recent orders to block duplicates
        self.last_call_time: float = 0.0         # to space out my calls

        if not is_testnet:
            # Only ask about permissions when real money is on the line.
            self.check_my_key_permissions()
        self.learn_coin_rules()

    # ------------------------------------------------------------------
    # Startup safety inspection
    # ------------------------------------------------------------------
    def check_my_key_permissions(self) -> None:
        """Ask Binance what this key is allowed to do. Withdrawals = NO GO."""
        answer = self.signed_call("GET", "/sapi/v1/account/apiRestrictions", {})
        if answer.get("enableWithdrawals"):
            raise SafetyShutdown(
                "STOP! My API key can withdraw coins. That's how bots get robbed. "
                "Make a new key with withdrawals switched OFF, then run me again."
            )
        if not answer.get("enableSpotTrading", True):
            raise SafetyShutdown("My key can't even trade. Make a spot-trading key.")
        log.info("Key check passed: withdrawals off, spot trading on, ip_locked=%s",
                 answer.get("ipRestrict"))
        if not answer.get("ipRestrict"):
            log.warning("My key is NOT locked to one IP address. Fix this before real money.")

    def learn_coin_rules(self) -> None:
        """Fetch each coin's minimum order sizes straight from the exchange."""
        info = self.public_call("GET", "/api/v3/exchangeInfo")
        for s in info.get("symbols", []):
            if s["symbol"] not in my_settings.my_coins:
                continue
            rule_book = {f["filterType"]: f for f in s["filters"]}
            notional_filter = rule_book.get("NOTIONAL") or rule_book.get("MIN_NOTIONAL") or {}
            self.coin_rules[s["symbol"]] = {
                "still_trading": s["status"] == "TRADING",
                "smallest_amount": float(rule_book["LOT_SIZE"]["minQty"]),
                "step_size": float(rule_book["LOT_SIZE"]["stepSize"]),
                "smallest_value": float(
                    notional_filter.get("minNotional", my_settings.smallest_order_usd)
                ),
            }

    # ------------------------------------------------------------------
    # Reading prices and candles
    # ------------------------------------------------------------------
    def get_price_now(self, coin_name: str) -> float:
        answer = self.public_call("GET", "/api/v3/ticker/price", {"symbol": coin_name})
        return float(answer["price"])

    def get_candles(self, coin_name: str, how_many: int = 120) -> List[dict]:
        """The last `how_many` candles, newest last. Same shape everywhere else."""
        raw = self.public_call(
            "GET", "/api/v3/klines",
            {"symbol": coin_name, "interval": my_settings.candle_size, "limit": how_many},
        )
        candles: List[dict] = []
        for one in raw:
            candles.append({
                "open_time": one[0],
                "open": float(one[1]),
                "high": float(one[2]),
                "low": float(one[3]),
                "close": float(one[4]),
                "volume": float(one[5]),
            })
        return candles

    def get_old_candles_page(self, coin_name: str, before_time: Optional[int]) -> List[list]:
        """
        Public method (fix: the old code reached into a private function).
        Gives one page of up to 1000 candles OLDER than `before_time`.
        Used by the time machine to download 2 years of history politely.
        """
        ask: Dict[str, Any] = {
            "symbol": coin_name, "interval": my_settings.candle_size, "limit": 1000,
        }
        if before_time is not None:
            ask["endTime"] = before_time
        return self.public_call("GET", "/api/v3/klines", ask)

    # ------------------------------------------------------------------
    # Placing an order -- with the full checklist first
    # ------------------------------------------------------------------
    def is_this_order_safe(self, coin_name: str, side: str, amount: float,
                           price_now: float) -> float:
        """
        All the boring-but-life-saving checks. Returns the tidied amount.
        Raises ExchangeProblem if anything smells wrong.
        """
        if side not in ("BUY", "SELL"):
            raise ExchangeProblem(f"'{side}' is not BUY or SELL.")
        if price_now <= 0:
            raise ExchangeProblem("Price can't be zero or negative.")
        if coin_name not in my_settings.my_coins:
            raise ExchangeProblem(f"{coin_name} is not on my allowed list.")

        rules = self.coin_rules.get(coin_name)
        if rules is None:
            raise ExchangeProblem(f"I have no rulebook for {coin_name}.")
        if not rules["still_trading"]:
            raise ExchangeProblem(f"{coin_name} is paused by the exchange.")

        # Round the amount down to a size the exchange will accept.
        step = rules["step_size"]
        tidy_amount = amount if step <= 0 else round(int(amount / step) * step, 8)

        if tidy_amount < rules["smallest_amount"]:
            raise ExchangeProblem(
                f"Amount {tidy_amount} is below the exchange minimum "
                f"{rules['smallest_amount']}."
            )
        if tidy_amount * price_now < rules["smallest_value"]:
            raise ExchangeProblem(
                f"Order worth {tidy_amount * price_now:.2f} USD is below the "
                f"{rules['smallest_value']:.2f} USD minimum."
            )
        return tidy_amount

    def place_market_order(self, coin_name: str, side: str, amount: float,
                           price_now: float) -> dict:
        tidy = self.is_this_order_safe(coin_name, side, amount, price_now)

        # Duplicate guard: the exact same order twice in a row gets rejected.
        stamp = f"{coin_name}:{side}:{round(tidy, 8)}:{round(price_now, 2)}"
        memory = self.known_orders.setdefault(coin_name, set())
        if stamp in memory:
            raise ExchangeProblem(f"Tried to send the same order twice: {stamp}")
        memory.add(stamp)

        answer = self.signed_call(
            "POST", "/api/v3/order",
            {"symbol": coin_name, "side": side, "type": "MARKET", "quantity": tidy},
        )
        log.info("ORDER DONE %s %s amount=%s id=%s",
                 side, coin_name, tidy, answer.get("orderId"))
        return answer

    # ------------------------------------------------------------------
    # The plumbing: signed / public calls, retries, speed limits
    # ------------------------------------------------------------------
    def _polite_pause(self) -> None:
        """Wait a bit between calls so Binance never sees me as a spammer."""
        since_last = time.time() - self.last_call_time
        if since_last < my_settings.wait_between_calls:
            time.sleep(my_settings.wait_between_calls - since_last)
        self.last_call_time = time.time()

    def public_call(self, method: str, path: str, params: Optional[dict] = None) -> Any:
        return self._make_call(method, path, params or {}, sign_it=False, try_number=1)

    def signed_call(self, method: str, path: str, params: dict,
                    try_number: int = 1) -> Any:
        return self._make_call(method, path, params, sign_it=True, try_number=try_number)

    def _make_call(self, method: str, path: str, params: dict,
                   sign_it: bool, try_number: int) -> Any:
        self._polite_pause()
        send_me = dict(params)

        if sign_it:
            # Fixes finding F4: build the string with urlencode (handles all
            # characters safely) instead of gluing text by hand.
            send_me["timestamp"] = int(time.time() * 1000)
            send_me["recvWindow"] = 5000
            text = urlencode(send_me)
            fingerprint = hmac.new(self.my_secret, text.encode(), hashlib.sha256)
            send_me["signature"] = fingerprint.hexdigest()

        try:
            answer = self.web.request(method, self.address + path,
                                      params=send_me, timeout=10)
            if answer.status_code == 429:
                # "Slow down please" -- wait exactly as long as they ask.
                nap = int(answer.headers.get("Retry-After", 5))
                log.warning("Exchange said slow down. Napping %s seconds.", nap)
                time.sleep(nap)
                raise ExchangeProblem("speed limit hit")
            if answer.status_code == 418:
                # IP banned. Do NOT keep trying; that only makes it worse.
                raise SafetyShutdown("My IP got banned by Binance. Stopping completely.")
            answer.raise_for_status()
            return answer.json()
        except requests.RequestException as oops:
            code = getattr(getattr(oops, "response", None), "status_code", None)
            if try_number < my_settings.max_retries:
                wait = my_settings.wait_between_calls * (2 ** (try_number - 1))
                log.warning("Call %s failed (code %s). Trying again in %.1fs.",
                            path, code, wait)
                time.sleep(wait)
                if sign_it:
                    return self.signed_call(method, path, params, try_number + 1)
                return self._make_call(method, path, params, False, try_number + 1)
            raise ExchangeProblem(f"Gave up on {path}: {oops}") from oops

# talk_to_binance.py
"""
The only file that speaks to Binance.
Keys come from .env only. They are never printed.
On real-money start I ask Binance what the key may do.
If it can withdraw, or if it is not locked to an IP, I shut down.
Every order is checked before it is sent.
"""

import hashlib
import hmac
import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests

import my_settings

log = logging.getLogger("bot.exchange")


class ExchangeProblem(Exception):
    """Something went wrong talking to Binance."""


class SafetyShutdown(Exception):
    """Something unsafe happened and I must stop NOW."""


class BinanceConnection:
    def __init__(self, my_key: str, my_secret: str, address: str, is_testnet: bool) -> None:
        self.my_key = my_key
        self.my_secret = my_secret.encode() if my_secret else b""
        self.address = address.rstrip("/")
        self.web = requests.Session()
        if my_key:
            self.web.headers.update({"X-MBX-APIKEY": my_key})

        self.coin_rules: Dict[str, dict] = {}
        self.known_orders: Dict[str, set] = {}
        self.last_call_time: float = 0.0

    # When we have no API key we are only doing a backtest → skip network calls
        if not my_key:
        # Put minimal hard-coded rules so the rest of the code does not crash
            for symbol in my_settings.my_coins:
                self.coin_rules[symbol] = {
                    "still_trading": True,
                    "smallest_amount": 0.00001,
                    "step_size": 0.00001,
                    "smallest_value": 5.0,
            }
        return

    if not is_testnet:
        self.check_my_key_permissions()
    self.learn_coin_rules()

    def check_my_key_permissions(self) -> None:
        """Ask Binance what this key is allowed to do. Fail closed."""
        answer = self.signed_call("GET", "/sapi/v1/account/apiRestrictions", {})
        if answer.get("enableWithdrawals"):
            raise SafetyShutdown(
                "STOP! My API key can withdraw coins. "
                "Make a new key with withdrawals switched OFF."
            )
        if not answer.get("enableSpotTrading", True):
            raise SafetyShutdown("My key cannot even trade spot. Make a spot-trading key.")
        if not answer.get("ipRestrict"):
            raise SafetyShutdown(
                "STOP! My API key is not locked to an IP address. "
                "Turn on IP restriction on Binance before real money."
            )
        log.info("Key check passed: withdrawals off, spot on, IP locked.")

    def learn_coin_rules(self) -> None:
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

    def get_price_now(self, coin_name: str) -> float:
        answer = self.public_call("GET", "/api/v3/ticker/price", {"symbol": coin_name})
        return float(answer["price"])

    def get_candles(self, coin_name: str, how_many: int = 120) -> List[dict]:
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

    def get_old_candles_page(self, coin_name: str, before_time: Optional[int] = None) -> List[list]:
        ask: Dict[str, Any] = {
            "symbol": coin_name, "interval": my_settings.candle_size, "limit": 1000,
        }
        if before_time is not None:
            ask["endTime"] = before_time
        return self.public_call("GET", "/api/v3/klines", ask)

    def is_this_order_safe(self, coin_name: str, side: str, amount: float,
                           price_now: float) -> float:
        if side not in ("BUY", "SELL"):
            raise ExchangeProblem(f"'{side}' is not BUY or SELL.")
        if price_now <= 0:
            raise ExchangeProblem("Price cannot be zero or negative.")
        if coin_name not in my_settings.my_coins:
            raise ExchangeProblem(f"{coin_name} is not on my allowed list.")

        rules = self.coin_rules.get(coin_name)
        if rules is None:
            raise ExchangeProblem(f"I have no rulebook for {coin_name}.")
        if not rules["still_trading"]:
            raise ExchangeProblem(f"{coin_name} is paused by the exchange.")

        step = rules["step_size"]
        tidy_amount = amount if step <= 0 else round(int(amount / step) * step, 8)

        if tidy_amount < rules["smallest_amount"]:
            raise ExchangeProblem(
                f"Amount {tidy_amount} is below the exchange minimum {rules['smallest_amount']}."
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

    def place_stop_loss(self, coin_name: str, amount: float, stop_price: float) -> Optional[dict]:
        """Try to put a stop-loss order on the exchange so a crash still protects me."""
        try:
            tidy = self.is_this_order_safe(coin_name, "SELL", amount, stop_price)
            answer = self.signed_call(
                "POST", "/api/v3/order",
                {
                    "symbol": coin_name,
                    "side": "SELL",
                    "type": "STOP_LOSS_LIMIT",
                    "quantity": tidy,
                    "stopPrice": round(stop_price, 2),
                    "price": round(stop_price * 0.995, 2),  # limit a little below
                    "timeInForce": "GTC",
                },
            )
            log.info("Exchange stop-loss placed for %s at %.2f", coin_name, stop_price)
            return answer
        except Exception as e:
            log.warning("Could not place exchange stop-loss for %s: %s", coin_name, e)
            return None

    def get_open_orders(self, coin_name: Optional[str] = None) -> List[dict]:
        params = {}
        if coin_name:
            params["symbol"] = coin_name
        return self.signed_call("GET", "/api/v3/openOrders", params)

    def cancel_order(self, coin_name: str, order_id: int) -> None:
        self.signed_call("DELETE", "/api/v3/order", {"symbol": coin_name, "orderId": order_id})

    def _polite_pause(self) -> None:
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
            send_me["timestamp"] = int(time.time() * 1000)
            send_me["recvWindow"] = 5000
            text = urlencode(send_me)
            fingerprint = hmac.new(self.my_secret, text.encode(), hashlib.sha256)
            send_me["signature"] = fingerprint.hexdigest()

        try:
            answer = self.web.request(method, self.address + path,
                                      params=send_me, timeout=10)
            if answer.status_code == 429:
                nap = int(answer.headers.get("Retry-After", 5))
                log.warning("Exchange said slow down. Napping %s seconds.", nap)
                time.sleep(nap)
                raise ExchangeProblem("speed limit hit")
            if answer.status_code == 418:
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
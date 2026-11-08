"""
my_settings.py
--------------
Loads configuration from two places:
  1. config.yaml  → all tunable parameters
  2. .env         → secrets and mode switches only

Never put secrets in config.yaml.
"""

import os
from pathlib import Path
from typing import Any, Dict, List

import yaml
from dotenv import load_dotenv

# ------------------------------------------------------------------
# Paths
# ------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

CONFIG_FILE = BASE_DIR / "config.yaml"


def _load_yaml() -> Dict[str, Any]:
    if not CONFIG_FILE.exists():
        raise SystemExit(f"Missing {CONFIG_FILE}. Please create config.yaml")
    with CONFIG_FILE.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


_cfg = _load_yaml()


def _text(key: str, default: str = "", required: bool = False) -> str:
    value = os.getenv(key, default)
    if required and not value.strip():
        raise SystemExit(f"I am missing the setting {key}. Please add it to .env")
    return value


def _yes_no(key: str, default: str = "false") -> bool:
    return _text(key, default).strip().lower() in ("true", "1", "yes")


# ------------------------------------------------------------------
# Mode & secrets (from .env only)
# ------------------------------------------------------------------
trading_mode: str = _text("TRADING_MODE", "BACKTEST").upper()
if trading_mode not in ("BACKTEST", "PAPER", "LIVE"):
    raise SystemExit("TRADING_MODE must be BACKTEST, PAPER or LIVE")

stop_everything: bool = _yes_no("EMERGENCY_STOP")

use_testnet: bool = _yes_no("USE_TESTNET", "true")
api_address: str = "https://testnet.binance.vision" if use_testnet else "https://api.binance.com"
api_key: str = _text("BINANCE_API_KEY", required=(trading_mode in ("PAPER", "LIVE")))
api_secret: str = _text("BINANCE_API_SECRET", required=(trading_mode in ("PAPER", "LIVE")))

log_file: Path = Path(_text("LOG_FILE", "bot.log"))

# ------------------------------------------------------------------
# Everything else comes from config.yaml
# ------------------------------------------------------------------
my_coins: List[str] = _cfg.get("my_coins", ["BTCUSDT", "ETHUSDT"])
candle_size: str = _cfg.get("candle_size", "1h")

# Trading plan - Entry
trend_line_length: int = int(_cfg.get("trend_line_length", 50))
rsi_length: int = int(_cfg.get("rsi_length", 14))
rsi_too_low: float = float(_cfg.get("rsi_too_low", 55.0))
rsi_too_high: float = float(_cfg.get("rsi_too_high", 70.0))
volume_average_length: int = int(_cfg.get("volume_average_length", 20))
bollinger_length: int = int(_cfg.get("bollinger_length", 20))
bollinger_width: float = float(_cfg.get("bollinger_width", 2.0))

# Trading plan - Exit
take_profit_percent: float = float(_cfg.get("take_profit_percent", 0.015))
trailing_stop_percent: float = float(_cfg.get("trailing_stop_percent", 0.01))
hard_stop_percent: float = float(_cfg.get("hard_stop_percent", 0.01))

# Safety
risk_one_percent: float = float(_cfg.get("risk_one_percent", 0.01))
max_trades_at_once: int = int(_cfg.get("max_trades_at_once", 2))
daily_loss_limit: float = float(_cfg.get("daily_loss_limit", 0.03))
daily_pause_hours: int = int(_cfg.get("daily_pause_hours", 24))
loss_streak_pause_hours: int = int(_cfg.get("loss_streak_pause_hours", 8))
too_crazy_volatility: float = float(_cfg.get("too_crazy_volatility", 4.0))
smallest_order_usd: float = float(_cfg.get("smallest_order_usd", 10.0))
quiet_news_hours_utc: List[int] = _cfg.get("quiet_news_hours_utc", [])

# Costs
fee_percent: float = float(_cfg.get("fee_percent", 0.001))
slippage_percent: float = float(_cfg.get("slippage_percent", 0.0005))

# Backtest & gates
backtest_years: int = int(_cfg.get("backtest_years", 2))
good_profit_factor: float = float(_cfg.get("good_profit_factor", 1.5))
safe_max_drawdown: float = float(_cfg.get("safe_max_drawdown", 0.15))
too_good_win_rate: float = float(_cfg.get("too_good_win_rate", 0.80))
min_trades_required: int = int(_cfg.get("min_trades_required", 30))
paper_days_needed: int = int(_cfg.get("paper_days_needed", 30))

# Technical
wait_between_calls: float = float(_cfg.get("wait_between_calls", 1.0))
max_retries: int = int(_cfg.get("max_retries", 3))

# Paths (derived)
results_folder: Path = BASE_DIR
paper_results_file: Path = results_folder / "paper_trading_results.json"
open_positions_file: Path = results_folder / ".open_positions.json"
backtest_history_file: Path = results_folder / "backtest_history.json"
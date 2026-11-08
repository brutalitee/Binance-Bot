# my_settings.py
"""
Every number and switch the bot uses lives here, in one place.
I read everything from a .env file so my secret keys are never written
in the code. I never commit .env to git.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


def _text(key: str, default: str = "", required: bool = False) -> str:
    value = os.getenv(key, default)
    if required and not value.strip():
        raise SystemExit(f"I am missing the setting {key}. Please add it to .env")
    return value


def _yes_no(key: str, default: str = "false") -> bool:
    return _text(key, default).strip().lower() in ("true", "1", "yes")


# ------------------------------------------------------------------
# What am I doing today?
# ------------------------------------------------------------------
trading_mode: str = _text("TRADING_MODE", "BACKTEST").upper()
if trading_mode not in ("BACKTEST", "PAPER", "LIVE"):
    raise SystemExit("TRADING_MODE must be BACKTEST, PAPER or LIVE")

stop_everything: bool = _yes_no("EMERGENCY_STOP")

# ------------------------------------------------------------------
# Talking to Binance. Testnet first, always.
# ------------------------------------------------------------------
use_testnet: bool = _yes_no("USE_TESTNET", "true")
api_address: str = "https://testnet.binance.vision" if use_testnet else "https://api.binance.com"
api_key: str = _text("BINANCE_API_KEY", required=(trading_mode in ("PAPER", "LIVE")))
api_secret: str = _text("BINANCE_API_SECRET", required=(trading_mode in ("PAPER", "LIVE")))

log_file: Path = Path(_text("LOG_FILE", "bot.log"))

# ------------------------------------------------------------------
# Which coins and which candles
# ------------------------------------------------------------------
my_coins: list = ["BTCUSDT", "ETHUSDT"]
candle_size: str = "1h"

# ------------------------------------------------------------------
# Safety rules
# ------------------------------------------------------------------
risk_one_percent: float = 0.01
max_trades_at_once: int = 2
daily_loss_limit: float = 0.03
daily_pause_hours: int = 24
loss_streak_pause_hours: int = 8
too_crazy_volatility: float = 4.0
quiet_news_hours_utc: list = []

# ------------------------------------------------------------------
# My trading plan  (loosened so we get more trades)
# ------------------------------------------------------------------
trend_line_length: int = 40            # was 50
rsi_length: int = 14
rsi_too_high: float = 70.0
rsi_too_low: float = 30.0              # was 35/40 – earlier entries
volume_average_length: int = 10        # was 15/20 – less strict volume
take_profit_percent: float = 0.025
trailing_stop_percent: float = 0.012
hard_stop_percent: float = 0.012

bollinger_length: int = 20
bollinger_width: float = 2.5           # was 2.2 – wider bands

# ------------------------------------------------------------------
# Honest costs
# ------------------------------------------------------------------
fee_percent: float = 0.001
slippage_percent: float = 0.0005

# ------------------------------------------------------------------
# Backtest and the gates to real money
# ------------------------------------------------------------------
backtest_years: int = 2
good_profit_factor: float = 1.5
safe_max_drawdown: float = 0.15
too_good_win_rate: float = 0.80
paper_days_needed: int = 30
results_folder: Path = Path(__file__).parent
paper_results_file: Path = results_folder / "paper_trading_results.json"
open_positions_file: Path = results_folder / ".open_positions.json"
backtest_history_file: Path = results_folder / "backtest_history.json"   # NEW

# ------------------------------------------------------------------
# Small safety floors for orders
# ------------------------------------------------------------------
smallest_order_usd: float = 10.0
wait_between_calls: float = 1.0
max_retries: int = 3
"""
my_settings.py
--------------
Every number and switch the bot uses lives here, in one place.
(This file used to be called config.py -- same job, friendlier name.)

I read everything from a .env file so my secret keys are never written
in the code. I never commit .env to git.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# .env sits next to this file. load_dotenv reads it into os.environ.
load_dotenv(Path(__file__).parent / ".env")


def _text(key: str, default: str = "", required: bool = False) -> str:
    """Read one setting from the environment. Stop the bot if it's required and missing."""
    value = os.getenv(key, default)
    if required and not value.strip():
        raise SystemExit(f"I am missing the setting {key}. Please add it to .env")
    return value


def _yes_no(key: str, default: str = "false") -> bool:
    """Turn 'true'/'yes'/'1' into True, anything else into False."""
    return _text(key, default).strip().lower() in ("true", "1", "yes")


# ------------------------------------------------------------------
# What am I doing today?
# BACKTEST = replay old candles, no money involved
# PAPER    = live prices, fake money
# LIVE     = real money (many gates must pass first -- see run_bot.py)
# ------------------------------------------------------------------
trading_mode: str = _text("TRADING_MODE", "BACKTEST").upper()
if trading_mode not in ("BACKTEST", "PAPER", "LIVE"):
    raise SystemExit("TRADING_MODE must be BACKTEST, PAPER or LIVE")

# Big red button. Setting this to true in .env freezes all trading instantly.
stop_everything: bool = _yes_no("EMERGENCY_STOP")

# ------------------------------------------------------------------
# Talking to Binance. Testnet first, always.
# ------------------------------------------------------------------
use_testnet: bool = _yes_no("USE_TESTNET", "true")
api_address: str = "https://testnet.binance.vision" if use_testnet else "https://api.binance.com"
api_key: str = _text("BINANCE_API_KEY", required=(trading_mode in ("PAPER", "LIVE")))
api_secret: str = _text("BINANCE_API_SECRET", required=(trading_mode in ("PAPER", "LIVE")))

# Where I keep my diary of everything the bot did.
log_file: Path = Path(_text("LOG_FILE", "bot.log"))

# ------------------------------------------------------------------
# Which coins and which candles
# ------------------------------------------------------------------
my_coins: list = ["BTCUSDT", "ETHUSDT"]        # only these two, ever
candle_size: str = "1h"                        # one-hour candles

# ------------------------------------------------------------------
# Safety rules (see safety_rules.py)
# ------------------------------------------------------------------
risk_one_percent: float = 0.01          # lose at most 1% of my money per trade
max_trades_at_once: int = 2             # never hold more than 2 coins
daily_loss_limit: float = 0.03          # if I lose 3% today, stop for a day
daily_pause_hours: int = 24
loss_streak_pause_hours: int = 8        # 3 losses in a row -> rest 8 hours
too_crazy_volatility: float = 4.0       # skip trades when prices swing more than 4%
quiet_news_hours_utc: list = []         # fill in hours to avoid, e.g. [12, 13, 14]

# ------------------------------------------------------------------
# My trading plan (see trading_plan.py)
# ------------------------------------------------------------------
trend_line_length: int = 50             # 50-candle average = the trend
rsi_length: int = 14
rsi_too_high: float = 70.0              # don't buy when everyone already bought
rsi_too_low: float = 55.0               # don't catch falling knives either
volume_average_length: int = 20
take_profit_percent: float = 0.015      # sell +1.5%
trailing_stop_percent: float = 0.01     # follow price up, sell if it drops 1% from the top
hard_stop_percent: float = 0.01         # emergency exit at -1%

# --- NEW: Bollinger Bands (added everywhere at once so test and live agree) ---
bollinger_length: int = 20              # middle line = 20-candle average
bollinger_width: float = 2.0            # bands sit 2 standard deviations away

# ------------------------------------------------------------------
# Honest costs. Fees eat profit, so I must count them.
# ------------------------------------------------------------------
fee_percent: float = 0.001              # 0.1% per side on Binance spot
slippage_percent: float = 0.0005        # prices move slightly before my order fills

# ------------------------------------------------------------------
# Backtest and the gates to real money
# ------------------------------------------------------------------
backtest_years: int = 2
good_profit_factor: float = 1.5         # winnings must be 1.5x the losses...
safe_max_drawdown: float = 0.15         # ...and worst losing streak < 15%
too_good_win_rate: float = 0.80         # winning >80% probably means I fooled myself
paper_days_needed: int = 30             # 30 winning paper days before LIVE
results_folder: Path = Path(__file__).parent
paper_results_file: Path = results_folder / "paper_trading_results.json"

# ------------------------------------------------------------------
# Small safety floors for orders
# ------------------------------------------------------------------
smallest_order_usd: float = 10.0        # Binance rejects tiny orders anyway
wait_between_calls: float = 1.0         # never spam the exchange
max_retries: int = 3
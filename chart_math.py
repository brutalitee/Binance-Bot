"""
chart_math.py
-------------
Just math on lists of prices. No internet, no money, no danger.
Used by BOTH the time machine and the live bot, so they always agree.
(Old name: indicators.py)
"""

from typing import List, Optional


def average(prices: List[float], length: int) -> Optional[float]:
    """Normal average of the last `length` prices. None if not enough data yet."""
    if len(prices) < length:
        return None
    last_few = prices[-length:]
    return sum(last_few) / length


def moving_average_line(prices: List[float], length: int) -> List[Optional[float]]:
    """Same average, but for every point in time. Used for drawing/checking the trend."""
    answer: List[Optional[float]] = []
    for i in range(len(prices)):
        if i + 1 < length:
            answer.append(None)  # not enough history yet
            continue
        window = prices[i + 1 - length: i + 1]
        answer.append(sum(window) / length)
    return answer


def rsi_line(prices: List[float], length: int = 14) -> List[Optional[float]]:
    """
    RSI = 'are we buying too eagerly?' score from 0 to 100.
    Above 70 = probably too high, below 30 = maybe too low.
    """
    n = len(prices)
    if n < length + 1:
        return [None] * n

    ups: List[float] = []
    downs: List[float] = []
    for i in range(1, n):
        change = prices[i] - prices[i - 1]
        ups.append(max(change, 0.0))      # how much we gained
        downs.append(max(-change, 0.0))   # how much we lost

    avg_up = sum(ups[:length]) / length
    avg_down = sum(downs[:length]) / length

    answer: List[Optional[float]] = [None] * length
    for i in range(length, n):
        # smoothing: mix yesterday's average with today's move (Wilder's method)
        avg_up = (avg_up * (length - 1) + ups[i - 1]) / length
        avg_down = (avg_down * (length - 1) + downs[i - 1]) / length
        if avg_down == 0:
            answer.append(100.0)
        else:
            strength = avg_up / avg_down
            answer.append(100.0 - (100.0 / (1.0 + strength)))
    return answer


def standard_deviation(numbers: List[float]) -> float:
    """How spread out the numbers are. Big number = wild, jumpy prices."""
    if not numbers:
        return 0.0
    avg = sum(numbers) / len(numbers)
    squared_gaps = [(x - avg) ** 2 for x in numbers]
    return (sum(squared_gaps) / len(numbers)) ** 0.5


def bollinger_bands(
    prices: List[float], length: int = 20, width: float = 2.0
) -> Optional[dict]:
    """
    Bollinger Bands: three lines drawn around the price.
      middle = the average price
      upper  = average + width * how-jumpy  (too expensive if we're way above it)
      lower  = average - width * how-jumpy
    NEW RULE: I only buy when the price is INSIDE the bands (not stretched
    above the upper band). Buying when price pokes far above the upper band
    usually ends with me paying the top price of a spike.
    """
    if len(prices) < length:
        return None
    window = prices[-length:]
    middle = sum(window) / length
    jumpiness = standard_deviation(window)
    return {
        "middle": middle,
        "upper": middle + width * jumpiness,
        "lower": middle - width * jumpiness,
    }


def how_jumpy_are_prices(prices: List[float], look_back: int = 20) -> float:
    """Percent-up-and-down swings over the last few candles. Used as a danger alarm."""
    if len(prices) < look_back + 1:
        return 0.0
    moves = []
    for i in range(len(prices) - look_back, len(prices)):
        if prices[i - 1] == 0:
            continue
        moves.append((prices[i] - prices[i - 1]) / prices[i - 1] * 100.0)
    if not moves:
        return 0.0
    avg = sum(moves) / len(moves)
    squared = sum((m - avg) ** 2 for m in moves) / len(moves)
    return squared ** 0.5

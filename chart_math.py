# chart_math.py
"""
Just math on lists of prices. No internet, no money, no danger.
Used by both the time machine and the live bot.
"""

from typing import List, Optional


def average(prices: List[float], length: int) -> Optional[float]:
    if len(prices) < length:
        return None
    last_few = prices[-length:]
    return sum(last_few) / length


def rsi_line(prices: List[float], length: int = 14) -> List[Optional[float]]:
    n = len(prices)
    if n < length + 1:
        return [None] * n

    ups: List[float] = []
    downs: List[float] = []
    for i in range(1, n):
        change = prices[i] - prices[i - 1]
        ups.append(max(change, 0.0))
        downs.append(max(-change, 0.0))

    avg_up = sum(ups[:length]) / length
    avg_down = sum(downs[:length]) / length

    answer: List[Optional[float]] = [None] * length
    for i in range(length, n):
        avg_up = (avg_up * (length - 1) + ups[i - 1]) / length
        avg_down = (avg_down * (length - 1) + downs[i - 1]) / length
        if avg_down == 0:
            answer.append(100.0)
        else:
            strength = avg_up / avg_down
            answer.append(100.0 - (100.0 / (1.0 + strength)))
    return answer


def standard_deviation(numbers: List[float]) -> float:
    if not numbers:
        return 0.0
    avg = sum(numbers) / len(numbers)
    squared_gaps = [(x - avg) ** 2 for x in numbers]
    return (sum(squared_gaps) / len(numbers)) ** 0.5


def bollinger_bands(
    prices: List[float], length: int = 20, width: float = 2.0
) -> Optional[dict]:
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
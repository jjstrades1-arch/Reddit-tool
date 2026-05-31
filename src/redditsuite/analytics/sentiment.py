"""Comment sentiment scoring via VADER (lexicon-based, tuned for social text).

Returns the VADER compound score in ``[-1, 1]``. VADER needs no training and
handles emoji, slang and emphasis well, which suits short Reddit comments.
"""

from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def _analyzer():
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

    return SentimentIntensityAnalyzer()


def score_text(text: str) -> float:
    """Return the VADER compound sentiment of ``text`` in [-1, 1]."""
    if not text or not text.strip():
        return 0.0
    return float(_analyzer().polarity_scores(text)["compound"])

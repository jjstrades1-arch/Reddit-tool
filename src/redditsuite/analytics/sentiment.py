"""Comment sentiment scoring.

Two backends, selected by ``Settings.sentiment_backend``:

* ``"vader"`` (default) -- lexicon-based, no training, tuned for short social
  text; handles emoji, slang and emphasis well.
* ``"transformer"`` -- a Hugging Face sentiment pipeline, only used if the
  ``transformers`` library is separately installed. It is intentionally *not* a
  declared dependency (it pulls in heavy ML packages); if it cannot be loaded we
  log once and fall back to VADER.

Both return a compound score in ``[-1, 1]``.
"""

from __future__ import annotations

from functools import lru_cache

from ..core.config import get_settings
from ..core.logging import get_logger

log = get_logger(__name__)


@lru_cache(maxsize=1)
def _vader():
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

    return SentimentIntensityAnalyzer()


def _vader_score(text: str) -> float:
    return float(_vader().polarity_scores(text)["compound"])


@lru_cache(maxsize=1)
def _transformer_pipeline():
    """Load a transformers sentiment pipeline, or None if unavailable."""
    try:
        from transformers import pipeline

        return pipeline("sentiment-analysis")
    except Exception as exc:  # pragma: no cover - depends on optional dep
        log.warning("Transformer sentiment unavailable (%s); using VADER.", exc)
        return None


def _transformer_score(text: str) -> float:  # pragma: no cover - optional dep
    pipe = _transformer_pipeline()
    if pipe is None:
        return _vader_score(text)
    result = pipe(text[:512])[0]
    score = float(result["score"])
    return score if result["label"].upper().startswith("POS") else -score


def score_text(text: str) -> float:
    """Return the compound sentiment of ``text`` in [-1, 1]."""
    if not text or not text.strip():
        return 0.0
    if get_settings().sentiment_backend == "transformer":
        return _transformer_score(text)
    return _vader_score(text)

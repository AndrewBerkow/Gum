"""Offline Jev stand-in: deterministic heuristics for safety, scope and complexity."""

import re

_INJECTION_PHRASES = ("ignore previous instructions", "system prompt", "jailbreak")
_COMPLEX_MARKERS = (
    "explain why",
    "compare",
    "design",
    "prove",
    "debug",
    "code",
    "analyze",
    "step by step",
    "plan",
)
_SIMPLE_MAX_WORDS = 12
_CONSONANT_RUN = re.compile(r"[^aeiouy\W\d_]{4,}", re.IGNORECASE)


def p_unsafe(text: str) -> float:
    lowered = text.lower()
    return 0.95 if any(phrase in lowered for phrase in _INJECTION_PHRASES) else 0.05


def _wordlike(word: str) -> bool:
    return bool(re.search(r"[aeiouy]", word, re.IGNORECASE)) and not _CONSONANT_RUN.search(word)


def scope_of(text: str) -> tuple[str, float]:
    chars = [c for c in text if not c.isspace()]
    words = re.findall(r"[^\W\d_]+", text)
    letters = sum(c.isalpha() for c in chars)
    if not chars or letters / len(chars) < 0.5 or not words:
        return "noise", 0.9
    if sum(_wordlike(w) for w in words) / len(words) < 0.5:
        return "noise", 0.9
    return "valid_request", 0.92


def complexity_of(text: str) -> tuple[str, float]:
    lowered = text.lower()
    if len(text.split()) < _SIMPLE_MAX_WORDS and not any(m in lowered for m in _COMPLEX_MARKERS):
        return "simple", 0.88
    return "complex", 0.85

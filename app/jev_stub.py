"""Offline Jev stand-in: deterministic heuristics for safety, scope and complexity."""

import asyncio
import json
import re

import httpx2

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


_LATENCY_S = 0.03
_CONFIDENCE = 0.8


def _choice_answer(choice: str, p: float, labels: list[str]) -> dict:
    others = [label for label in labels if label != choice]
    probabilities = {choice: p, **{label: (1 - p) / len(others) for label in others}}
    return {"type": "choice", "choice": choice, "probabilities": probabilities, "confidence": _CONFIDENCE}


def stub_response(body: dict) -> dict:
    """Build a wire-format response answering only the question ids in `body`."""
    text = body["state"]["latest"]["content"]
    questions = body.get("questions", {})
    answers: dict[str, dict] = {}
    if "unsafe" in questions:
        answers["unsafe"] = {"type": "noul", "noul": p_unsafe(text)}
    if "scope" in questions:
        choice, p = scope_of(text)
        labels = list(questions["scope"].get("criteria", {}))
        answers["scope"] = _choice_answer(choice, p, labels or ["valid_request", "noise", "out_of_scope"])
    if "complexity" in questions:
        choice, p = complexity_of(text)
        labels = list(questions["complexity"].get("criteria", {}))
        answers["complexity"] = _choice_answer(choice, p, labels or ["simple", "complex"])
    return {
        "model": body.get("model", "jev-stub"),
        "answers": answers,
        "usage": {"input_tokens": len(text.split()), "output_tokens": len(answers)},
    }


def make_stub_transport(latency_s: float = _LATENCY_S) -> httpx2.MockTransport:
    """An httpx2 transport that serves the heuristic /v1/systemone handler."""

    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method != "POST" or request.url.path != "/v1/systemone":
            return httpx2.Response(404, json={"error": "not found"})
        if latency_s:
            await asyncio.sleep(latency_s)
        return httpx2.Response(200, json=stub_response(json.loads(request.content)))

    return httpx2.MockTransport(handler)

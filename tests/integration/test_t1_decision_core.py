"""Top-level integration tests for t1: scaffold, config, state and the Jev decision core."""

import asyncio
import importlib
import json
import os
import re
import subprocess
import sys
import tomllib
import typing
from pathlib import Path

import httpx2
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_typesafe import (
    Choice,
    ClassifierResponse,
    Noul,
)
from langchain_typesafe.client import (
    TypeSafeAPIError,
    TypeSafeInternalServerError,
)

ROOT = Path(__file__).resolve().parents[2]

# Set at collection time, before any fixture runs, to prove the autouse fixture clears them.
os.environ["LANGCHAIN_API_KEY"] = "lsv2_pt_leaked"
os.environ["LANGSMITH_API_KEY"] = "lsv2_leaked"
os.environ["GOOGLE_API_KEY"] = "AIzaLEAKED123"
os.environ["TYPESAFE_API_KEY"] = "ts_live_leaked"

TIERS = {"flash": "m-flash", "lite": "m-lite"}


def mod(name):
    return importlib.import_module(name)


# ---------------------------------------------------------------- helpers


def scope_probs(label, p):
    others = [x for x in ("valid_request", "noise", "out_of_scope") if x != label]
    probs = {label: p}
    for o in others:
        probs[o] = (1 - p) / 2
    return probs


def make_response(
    p_unsafe=0.05,
    scope=("valid_request", 0.92),
    p_simple=0.88,
    request_id=None,
    drop=(),
):
    label, p = scope
    answers = {
        "unsafe": {"type": "noul", "noul": p_unsafe},
        "scope": {
            "type": "choice",
            "choice": label,
            "probabilities": scope_probs(label, p),
            "confidence": 0.8,
        },
        "complexity": {
            "type": "choice",
            "choice": "simple" if p_simple >= 0.5 else "complex",
            "probabilities": {"simple": p_simple, "complex": 1 - p_simple},
            "confidence": 0.77,
        },
    }
    for d in drop:
        answers.pop(d)
    return ClassifierResponse.model_validate(
        {
            "model": "jev-latest",
            "answers": answers,
            "usage": {"input_tokens": 10, "output_tokens": 3},
            "request_id": request_id,
        }
    )


class FakeClassifier:
    def __init__(self, response=None, exc=None, delay=0.0):
        self.response = response
        self.exc = exc
        self.delay = delay
        self.calls = []

    async def ainvoke(self, request, *args, **kwargs):
        self.calls.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        else:
            await asyncio.sleep(0.002)
        if self.exc:
            raise self.exc
        return self.response


def evaluate(response, *, requested_tier="auto", block=0.7, lite=0.7):
    jev = mod("app.jev")
    return jev.evaluate(
        response,
        block_threshold=block,
        route_lite_threshold=lite,
        requested_tier=requested_tier,
        tiers=TIERS,
        latency_ms=12.5,
        jev_model="jev-latest",
    )


def blocked_ai(text="nope"):
    return AIMessage(text, additional_kwargs={"jev_blocked": True})


# ---------------------------------------------------------------- scaffold


def test_scaffold_pyproject_requires_python_312_and_no_openrouter():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert data["project"]["requires-python"].startswith(">=3.12")
    assert "openrouter" not in json.dumps(data).lower()
    assert (ROOT / "app" / "__init__.py").exists()


def test_scaffold_gitignore_covers_env_and_logs():
    text = (ROOT / ".gitignore").read_text()
    assert re.search(r"^\.env$", text, re.M)
    assert re.search(r"^logs/?$", text, re.M)


def test_scaffold_env_example_is_verbatim_from_plan():
    plan = (ROOT / "PLAN.md").read_text()
    anchor = plan.index("`.env.example` is committed")
    start = plan.index("```\n", anchor) + 4
    end = plan.index("\n```", start)
    assert (ROOT / ".env.example").read_text().strip() == plan[start:end].strip()


def test_scaffold_readme_records_httpx2_mocktransport_spike_result():
    readme = (ROOT / "README.md").read_text()
    assert "httpx2" in readme and "MockTransport" in readme
    assert hasattr(httpx2, "MockTransport")


# ---------------------------------------------------------------- config


def test_settings_defaults_load():
    s = mod("app.config").Settings(_env_file=None)
    assert s.jev_backend == "live"
    assert s.jev_model == "jev-latest"
    assert s.typesafe_base_url == "https://api.typesafe.ai"
    assert s.chat_provider == "google_genai"
    assert s.chat_model_flash == "gemini-3.8-flash"
    assert s.chat_model_lite == "gemini-3.5-flash-lite"
    assert s.block_threshold == 0.7
    assert s.route_lite_threshold == 0.7
    assert s.guardrail_timeout_s == 2.0
    assert s.guardrail_context_turns == 2
    assert s.max_message_chars == 4000
    assert s.log_messages is False
    assert s.decision_log_path == "logs/decisions.jsonl"
    assert s.model_prices == {}
    assert s.typesafe_api_key is None and s.google_api_key is None


def test_settings_env_vars_override_defaults(monkeypatch):
    for k, v in {
        "JEV_BACKEND": "stub",
        "CHAT_PROVIDER": "fake",
        "CHAT_MODEL_LITE": "custom-lite",
        "BLOCK_THRESHOLD": "0.5",
        "ROUTE_LITE_THRESHOLD": "0.9",
        "GUARDRAIL_TIMEOUT_S": "5",
        "GUARDRAIL_CONTEXT_TURNS": "4",
        "LOG_MESSAGES": "true",
    }.items():
        monkeypatch.setenv(k, v)
    s = mod("app.config").Settings(_env_file=None)
    assert s.jev_backend == "stub"
    assert s.chat_provider == "fake"
    assert s.chat_model_lite == "custom-lite"
    assert s.chat_model_flash == "gemini-3.8-flash"
    assert s.block_threshold == 0.5
    assert s.route_lite_threshold == 0.9
    assert s.guardrail_timeout_s == 5.0
    assert s.guardrail_context_turns == 4
    assert s.log_messages is True


@pytest.mark.parametrize("field", ["block_threshold", "route_lite_threshold"])
@pytest.mark.parametrize("bad", [-0.01, 1.01, 7])
def test_settings_thresholds_outside_unit_interval_rejected(field, bad):
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        mod("app.config").Settings(_env_file=None, **{field: bad})


@pytest.mark.parametrize("ok", [0.0, 1.0])
def test_settings_threshold_bounds_inclusive(ok):
    s = mod("app.config").Settings(_env_file=None, block_threshold=ok, route_lite_threshold=ok)
    assert s.block_threshold == ok


def test_settings_model_prices_parse_from_json(monkeypatch):
    monkeypatch.setenv(
        "MODEL_PRICES",
        json.dumps({"m-flash": {"input_per_mtok": 1.5, "output_per_mtok": 6}}),
    )
    s = mod("app.config").Settings(_env_file=None)
    price = s.model_prices["m-flash"]
    assert price.input_per_mtok == 1.5
    assert price.output_per_mtok == 6


def test_settings_invalid_model_prices_json_rejected(monkeypatch):
    config = mod("app.config")
    monkeypatch.setenv("MODEL_PRICES", "{}")
    assert config.Settings(_env_file=None).model_prices == {}
    monkeypatch.setenv("MODEL_PRICES", "{not json")
    with pytest.raises(ValueError):
        config.Settings(_env_file=None)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("ts_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx", False),
        ("AIzaxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", False),
        ("", False),
        (None, False),
        ("ts_live_abc123", True),
    ],
)
def test_has_real_key(value, expected):
    assert mod("app.config").has_real_key(value) is expected


def test_gemini_api_key_alone_populates_google_api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaTEST123")
    s = mod("app.config").Settings(_env_file=None)
    assert s.google_api_key.get_secret_value() == "AIzaTEST123"


def test_settings_ignores_dotenv_file_when_env_file_none(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("TYPESAFE_API_KEY=ts_live_fromfile\n")
    monkeypatch.chdir(tmp_path)
    s = mod("app.config").Settings(_env_file=None)
    assert s.typesafe_api_key is None


def test_config_error_is_an_exception():
    assert issubclass(mod("app.config").ConfigError, Exception)


def test_importing_app_with_no_env_vars_does_not_crash():
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")}
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.config, app.state, app.jev; app.config.Settings()",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_conftest_autouse_fixture_clears_tracing_and_provider_keys():
    for name in (
        "LANGCHAIN_API_KEY",
        "LANGSMITH_API_KEY",
        "GOOGLE_API_KEY",
        "TYPESAFE_API_KEY",
    ):
        assert name not in os.environ
    assert os.environ.get("LANGCHAIN_TRACING_V2", "false") != "true"
    s = mod("app.config").Settings(_env_file=None)
    assert s.typesafe_api_key is None and s.google_api_key is None


# ---------------------------------------------------------------- state


def test_add_messages_reducer_appends_on_chat_state():
    state = mod("app.state")
    hints = typing.get_type_hints(state.ChatState, include_extras=True)
    reducer = hints["messages"].__metadata__[0]
    out = reducer([HumanMessage("a")], [AIMessage("b")])
    assert [m.content for m in out] == ["a", "b"]
    assert set(hints) == {
        "messages",
        "requested_tier",
        "guardrail_passed",
        "jev_decision",
        "route",
    }


def test_jev_and_route_decisions_round_trip_through_json():
    state = mod("app.state")
    assert set(state.JevDecision.__annotations__) == {
        "status",
        "reason",
        "confidence",
        "p_unsafe",
        "scope",
        "scope_probabilities",
        "flags",
        "latency_ms",
        "jev_model",
        "request_id",
    }
    assert set(state.RouteDecision.__annotations__) == {
        "tier",
        "model",
        "source",
        "jev_tier",
        "p_simple",
        "complexity_confidence",
    }
    gate, route = evaluate(make_response(request_id="r1"))
    assert json.loads(json.dumps(gate)) == gate
    assert json.loads(json.dumps(route)) == route


# ---------------------------------------------------------------- QUESTIONS / build_request


def test_questions_ids_types_and_labels():
    q = mod("app.jev").QUESTIONS
    assert set(q) == {"unsafe", "scope", "complexity"}
    assert isinstance(q["unsafe"], Noul)
    assert isinstance(q["scope"], Choice)
    assert isinstance(q["complexity"], Choice)
    assert set(q["scope"].criteria) == {"valid_request", "noise", "out_of_scope"}
    assert set(q["complexity"].criteria) == {"simple", "complex"}
    assert q["unsafe"].criteria is not None


def test_build_request_latest_is_last_human_message():
    jev = mod("app.jev")
    msgs = [HumanMessage("h1"), AIMessage("a1"), HumanMessage("h2")]
    req = jev.build_request(msgs, 2)
    assert req["state"]["latest"].content == "h2"
    assert isinstance(req["state"]["latest"], HumanMessage)
    assert set(req["questions"]) == {"unsafe", "scope", "complexity"}


def test_build_request_recent_is_capped_at_context_turns():
    jev = mod("app.jev")
    msgs = []
    for i in range(1, 6):
        msgs += [HumanMessage(f"h{i}"), AIMessage(f"a{i}")]
    msgs.append(HumanMessage("latest-q"))
    req = jev.build_request(msgs, 2)
    recent = [m.content for m in req["state"]["recent"]]
    assert len(recent) <= 2 * 2
    assert "a5" in recent
    assert "h1" not in recent and "a1" not in recent
    assert jev.build_request(msgs, 0)["state"]["recent"] == []


def test_build_request_recent_excludes_blocked_pairs():
    jev = mod("app.jev")
    msgs = [
        HumanMessage("h1"),
        AIMessage("a1"),
        HumanMessage("evil-injection"),
        blocked_ai("canned-rejection"),
        HumanMessage("h3"),
        AIMessage("a3"),
        HumanMessage("latest-q"),
    ]
    req = jev.build_request(msgs, 5)
    recent = [m.content for m in req["state"]["recent"]]
    assert "evil-injection" not in recent
    assert "canned-rejection" not in recent
    assert "a3" in recent and "h1" in recent


def test_build_request_empty_history_raises_value_error():
    with pytest.raises(ValueError):
        mod("app.jev").build_request([], 2)


# ---------------------------------------------------------------- evaluate: gate rows


@pytest.mark.parametrize(
    "p_unsafe,scope,status,reason,conf",
    [
        (0.95, ("valid_request", 0.9), "blocked", "unsafe", 0.95),
        (0.71, ("valid_request", 0.9), "blocked", "unsafe", 0.71),
        (0.70, ("valid_request", 0.9), "passed", None, None),
        (0.1, ("noise", 0.85), "blocked", "noise", 0.85),
        (0.1, ("out_of_scope", 0.9), "blocked", "out_of_scope", 0.9),
        (0.1, ("noise", 0.6), "passed", None, None),
        (0.8, ("noise", 0.9), "blocked", "unsafe", 0.8),
        (0.08, ("valid_request", 0.92), "passed", None, 0.92),
    ],
)
def test_evaluate_gate_rows(p_unsafe, scope, status, reason, conf):
    gate, route = evaluate(make_response(p_unsafe=p_unsafe, scope=scope))
    assert gate["status"] == status
    assert gate["reason"] == reason
    if conf is not None:
        assert gate["confidence"] == pytest.approx(conf)
    if status == "blocked":
        assert route is None
    else:
        assert route is not None


def test_evaluate_boundary_070_passes_and_071_blocks_strictly_greater():
    assert evaluate(make_response(p_unsafe=0.70))[0]["status"] == "passed"
    assert evaluate(make_response(p_unsafe=0.71))[0]["status"] == "blocked"
    assert evaluate(make_response(scope=("noise", 0.70)))[0]["status"] == "passed"
    assert evaluate(make_response(scope=("noise", 0.71)))[0]["status"] == "blocked"


def test_evaluate_safety_outranks_scope_but_keeps_signals():
    gate, route = evaluate(make_response(p_unsafe=0.8, scope=("noise", 0.9)))
    assert gate["reason"] == "unsafe"
    assert route is None
    assert gate["p_unsafe"] == pytest.approx(0.8)
    assert gate["scope"] == "noise"


def test_evaluate_ambiguous_scope_passes_with_flag():
    gate, route = evaluate(make_response(p_unsafe=0.1, scope=("noise", 0.6)))
    assert gate["status"] == "passed"
    assert gate["flags"] == ["ambiguous_scope"]
    assert route is not None


def test_evaluate_clean_pass_has_no_flags_and_full_metadata():
    gate, _ = evaluate(make_response(p_unsafe=0.08, request_id="req-9"))
    assert gate["flags"] == []
    assert gate["p_unsafe"] == pytest.approx(0.08)
    assert gate["scope"] == "valid_request"
    assert gate["scope_probabilities"]["valid_request"] == pytest.approx(0.92)
    assert gate["latency_ms"] == 12.5
    assert gate["jev_model"] == "jev-latest"
    assert gate["request_id"] == "req-9"


def test_evaluate_pass_confidence_is_weakest_link():
    gate, _ = evaluate(make_response(p_unsafe=0.4, scope=("valid_request", 0.9)))
    assert gate["confidence"] == pytest.approx(0.6)


@pytest.mark.parametrize("missing", ["unsafe", "scope", "complexity"])
def test_evaluate_missing_answer_is_error_jev_error_no_route(missing):
    gate, route = evaluate(make_response(drop=(missing,)))
    assert gate["status"] == "error"
    assert gate["reason"] == "jev_error"
    assert route is None


# ---------------------------------------------------------------- evaluate: route rows


@pytest.mark.parametrize(
    "p_simple,requested,tier,source,jev_tier",
    [
        (0.88, "auto", "lite", "jev", "lite"),
        (0.70, "auto", "lite", "jev", "lite"),
        (0.69, "auto", "flash", "jev", "flash"),
        (0.50, "auto", "flash", "jev", "flash"),
        (0.10, "auto", "flash", "jev", "flash"),
        (0.88, "flash", "flash", "override", "lite"),
        (0.10, "lite", "lite", "override", "flash"),
    ],
)
def test_evaluate_route_rows(p_simple, requested, tier, source, jev_tier):
    gate, route = evaluate(make_response(p_simple=p_simple), requested_tier=requested)
    assert gate["status"] == "passed"
    assert route["tier"] == tier
    assert route["source"] == source
    assert route["jev_tier"] == jev_tier
    assert route["model"] == TIERS[tier]
    assert route["p_simple"] == pytest.approx(p_simple)
    assert route["complexity_confidence"] == pytest.approx(0.77)


def test_evaluate_route_threshold_is_configurable():
    _, route = evaluate(make_response(p_simple=0.8), lite=0.9)
    assert route["tier"] == "flash"
    _, route = evaluate(make_response(p_simple=0.8), lite=0.8)
    assert route["tier"] == "lite"


def test_evaluate_block_threshold_is_configurable():
    assert evaluate(make_response(p_unsafe=0.5), block=0.4)[0]["status"] == "blocked"


def test_evaluate_override_same_as_jev_is_still_source_override():
    _, route = evaluate(make_response(p_simple=0.9), requested_tier="lite")
    assert route["source"] == "override"
    assert route["jev_tier"] == "lite"


# ---------------------------------------------------------------- jev_gate node


def settings(**kw):
    return mod("app.config").Settings(_env_file=None, jev_backend="stub", chat_provider="fake", **kw)


def gate_state(text="hello there", tier="auto", history=()):
    return {
        "messages": [*history, HumanMessage(text)],
        "requested_tier": tier,
        "guardrail_passed": False,
        "jev_decision": None,
        "route": None,
    }


async def run_node(classifier, state=None, **kw):
    node = mod("app.jev").make_jev_gate_node(classifier, settings(**kw))
    return await node(state or gate_state())


async def test_jev_gate_pass_routes_and_appends_nothing():
    fake = FakeClassifier(make_response(request_id="req-1"))
    out = await run_node(fake)
    assert out["guardrail_passed"] is True
    assert out["jev_decision"]["status"] == "passed"
    assert out["route"]["tier"] == "lite"
    assert out["route"]["model"] == "gemini-3.5-flash-lite"
    assert not [m for m in out.get("messages") or []]


async def test_jev_gate_block_appends_canned_rejection_message():
    jev = mod("app.jev")
    fake = FakeClassifier(make_response(p_unsafe=0.95))
    out = await run_node(fake)
    assert out["guardrail_passed"] is False
    assert out["jev_decision"]["status"] == "blocked"
    assert out["jev_decision"]["reason"] == "unsafe"
    assert out["route"] is None
    (msg,) = out["messages"]
    assert isinstance(msg, AIMessage)
    assert msg.content == jev.REJECTION_MESSAGES["unsafe"]
    assert msg.additional_kwargs["jev_blocked"] is True


@pytest.mark.parametrize(
    "exc",
    [
        TypeSafeInternalServerError(500, None, httpx2.Headers({})),
        TypeSafeAPIError(401, None, httpx2.Headers({})),
    ],
)
async def test_jev_gate_typesafe_api_error_fails_closed(exc):
    jev = mod("app.jev")
    out = await run_node(FakeClassifier(exc=exc))
    assert out["guardrail_passed"] is False
    assert out["jev_decision"]["status"] == "error"
    assert out["jev_decision"]["reason"] == "jev_error"
    assert out["route"] is None
    (msg,) = out["messages"]
    assert msg.content == jev.REJECTION_MESSAGES["jev_error"]
    assert msg.additional_kwargs["jev_blocked"] is True


async def test_jev_gate_unexpected_exception_fails_closed():
    out = await run_node(FakeClassifier(exc=RuntimeError("boom")))
    assert out["guardrail_passed"] is False
    assert out["jev_decision"]["status"] == "error"
    assert out["route"] is None


async def test_jev_gate_timeout_fails_closed_promptly():
    fake = FakeClassifier(make_response(), delay=1.0)
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    out = await run_node(fake, guardrail_timeout_s=0.05)
    assert loop.time() - t0 < 0.8
    assert out["guardrail_passed"] is False
    assert out["jev_decision"]["status"] == "error"
    assert out["jev_decision"]["reason"] == "jev_error"
    assert out["route"] is None
    assert out["messages"][0].additional_kwargs["jev_blocked"] is True


async def test_jev_gate_error_decision_is_json_serializable():
    out = await run_node(FakeClassifier(exc=RuntimeError("boom")))
    json.dumps(out["jev_decision"])


async def test_jev_gate_makes_exactly_one_call_with_all_three_questions():
    fake = FakeClassifier(make_response())
    await run_node(fake, state=gate_state("what is 2+2?"))
    assert len(fake.calls) == 1
    req = fake.calls[0]
    assert set(req["questions"]) == {"unsafe", "scope", "complexity"}
    assert req["state"]["latest"].content == "what is 2+2?"


async def test_jev_gate_blocked_history_not_sent_as_recent_context():
    fake = FakeClassifier(make_response())
    history = [HumanMessage("evil-injection"), blocked_ai("canned-rejection")]
    await run_node(fake, state=gate_state("hi", history=history))
    recent = [m.content for m in fake.calls[0]["state"]["recent"]]
    assert "evil-injection" not in recent and "canned-rejection" not in recent


async def test_jev_gate_latency_ms_positive_and_request_id_propagated():
    out = await run_node(FakeClassifier(make_response(request_id="req-42")))
    assert out["jev_decision"]["latency_ms"] > 0
    assert out["jev_decision"]["request_id"] == "req-42"


async def test_jev_gate_error_latency_ms_positive():
    out = await run_node(FakeClassifier(exc=RuntimeError("boom")))
    assert out["jev_decision"]["latency_ms"] > 0


async def test_jev_gate_requested_tier_override_is_honoured():
    out = await run_node(FakeClassifier(make_response(p_simple=0.9)), state=gate_state(tier="flash"))
    assert out["route"]["tier"] == "flash"
    assert out["route"]["source"] == "override"
    assert out["route"]["jev_tier"] == "lite"
    assert out["route"]["model"] == "gemini-3.8-flash"

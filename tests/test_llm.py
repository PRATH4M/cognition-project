"""OpenRouter client tests using respx mocks only; no paid calls."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest
import respx
from helpers import (
    FakeBriefGenerator,
    make_contributor,
    make_contributors_result,
    make_report,
)
from pydantic import SecretStr

from app.errors import BriefGenerationError
from app.llm import (
    MAX_README_CHARS,
    MAX_TOKENS,
    BriefGenerator,
    brief_context,
    validate_brief,
)
from app.models import Brief, BriefPoint

URL = "https://openrouter.ai/api/v1/chat/completions"


def sample_report() -> Any:
    """Return a report with one contributor and a commit count."""
    return make_report(
        contributors=make_contributors_result([make_contributor("alice", 10)]),
        commit_count=1234,
    )


def completion(content: Any, finish_reason: str = "stop") -> dict[str, Any]:
    """Return a chat-completion payload."""
    return {
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content},
            }
        ]
    }


def brief_json(**overrides: Any) -> str:
    """Return a valid brief JSON string."""
    data: dict[str, Any] = {
        "summary": "A demo repo.",
        "strengths": [{"text": "Active", "fields": ["total_commits"]}],
        "risks": [{"text": "Risky", "fields": ["bus_factor_top1"]}],
        "getting_started": [{"text": "Start", "fields": ["contributors"]}],
    }
    data.update(overrides)
    return json.dumps(data)


async def make_generator() -> BriefGenerator:
    """Return a generator; the httpx client is closed by respx teardown."""
    return BriefGenerator(SecretStr("test-openrouter-key"), "test/model")


@respx.mock
async def test_request_shape() -> None:
    """The request hits OpenRouter with auth, model, schema, and provider flags."""
    route = respx.post(URL).respond(200, json=completion(brief_json()))
    generator = await make_generator()
    await generator.generate(sample_report(), "# Hi", is_private=False)
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer test-openrouter-key"
    body = json.loads(request.content)
    assert body["model"] == "test/model"
    assert body["max_tokens"] == MAX_TOKENS
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == "repo_brief"
    assert body["provider"]["require_parameters"] is True
    assert "zdr" not in body["provider"]
    await generator.aclose()


@respx.mock
async def test_zdr_only_for_private() -> None:
    """Private repos request zero data retention; public ones do not."""
    route = respx.post(URL).respond(200, json=completion(brief_json()))
    generator = await make_generator()
    await generator.generate(sample_report(), None, is_private=True)
    body = json.loads(route.calls.last.request.content)
    assert body["provider"]["zdr"] is True
    await generator.aclose()


@respx.mock
async def test_prompt_contents() -> None:
    """The prompt carries metrics, top contributors, and truncated README."""
    route = respx.post(URL).respond(200, json=completion(brief_json()))
    generator = await make_generator()
    readme = "x" * (MAX_README_CHARS + 500)
    await generator.generate(sample_report(), readme, is_private=False)
    body = json.loads(route.calls.last.request.content)
    messages = body["messages"]
    assert "untrusted" in messages[0]["content"]
    user = json.loads(messages[1]["content"])
    assert user["readme"] == "x" * MAX_README_CHARS
    context = user["metrics_context"]
    assert context["metadata"]["full_name"] == "octo/repo"
    assert context["metrics"]["total_commits"] == 1234
    assert context["contributors"] == [{"login": "alice", "commits": 10}]
    assert "avatar" not in messages[1]["content"]
    await generator.aclose()


@respx.mock
async def test_valid_response_parses() -> None:
    """A well-formed reply becomes a GeneratedBrief."""
    respx.post(URL).respond(200, json=completion(brief_json()))
    generator = await make_generator()
    brief = await generator.generate(sample_report(), None, is_private=False)
    assert brief.summary == "A demo repo."
    assert len(brief.strengths) == 1
    assert brief.dropped_points == 0
    await generator.aclose()


@respx.mock
async def test_drops_ungrounded_and_trims() -> None:
    """Points with unknown or missing fields are dropped; lists trim to 3."""
    strengths = [{"text": f"Good {i}", "fields": ["total_commits"]} for i in range(5)] + [
        {"text": "Bogus", "fields": ["not_a_field"]},
        {"text": "No fields", "fields": []},
    ]
    respx.post(URL).respond(200, json=completion(brief_json(strengths=strengths)))
    generator = await make_generator()
    brief = await generator.generate(sample_report(), None, is_private=False)
    assert len(brief.strengths) == 3
    assert brief.dropped_points == 2
    await generator.aclose()


@respx.mock
async def test_finish_reason_other_than_stop_fails() -> None:
    """Truncated replies are failures."""
    respx.post(URL).respond(200, json=completion(brief_json(), "length"))
    generator = await make_generator()
    with pytest.raises(BriefGenerationError):
        await generator.generate(sample_report(), None, is_private=False)
    await generator.aclose()


@respx.mock
async def test_invalid_json_fails() -> None:
    """Non-JSON content is a failure."""
    respx.post(URL).respond(200, json=completion("not json at all"))
    generator = await make_generator()
    with pytest.raises(BriefGenerationError):
        await generator.generate(sample_report(), None, is_private=False)
    await generator.aclose()


@respx.mock
async def test_wrong_shape_fails() -> None:
    """JSON that does not match the brief schema is a failure."""
    respx.post(URL).respond(200, json=completion(json.dumps({"foo": 1})))
    generator = await make_generator()
    with pytest.raises(BriefGenerationError):
        await generator.generate(sample_report(), None, is_private=False)
    await generator.aclose()


@respx.mock
async def test_http_error_fails() -> None:
    """Non-200 OpenRouter responses are failures."""
    respx.post(URL).respond(500, json={"error": "boom"})
    generator = await make_generator()
    with pytest.raises(BriefGenerationError):
        await generator.generate(sample_report(), None, is_private=False)
    await generator.aclose()


@respx.mock
async def test_timeout_fails() -> None:
    """Network timeouts are failures."""

    async def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    respx.post(URL).mock(side_effect=timeout)
    generator = await make_generator()
    with pytest.raises(BriefGenerationError):
        await generator.generate(sample_report(), None, is_private=False)
    await generator.aclose()


@respx.mock
async def test_readme_content_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    """README text never appears in log output."""
    word = "UNIQUE_README_WORD_XYZ_123"
    respx.post(URL).respond(200, json=completion(brief_json()))
    generator = await make_generator()
    with caplog.at_level(logging.DEBUG):
        await generator.generate(sample_report(), f"# Title\n{word}", is_private=False)
    assert word not in caplog.text
    await generator.aclose()


def test_brief_context_allowed_fields() -> None:
    """Citable fields come from the context keys."""
    _, allowed = brief_context(sample_report())
    assert "total_commits" in allowed
    assert "stars" in allowed
    assert "contributors" in allowed
    assert "avatar_url" not in allowed


def test_validate_brief_units() -> None:
    """validate_brief drops ungrounded points without an LLM call."""
    _, allowed = brief_context(sample_report())
    brief = Brief.model_validate(
        {
            "summary": "s",
            "strengths": [
                {"text": "ok", "fields": ["stars"]},
                {"text": "bad", "fields": ["nope"]},
                {"text": "empty", "fields": []},
            ],
            "risks": [],
            "getting_started": [],
        }
    )
    result = validate_brief(brief, allowed)
    assert [p.text for p in result.strengths] == ["ok"]
    assert result.dropped_points == 2


def test_fake_brief_generator_records() -> None:
    """The fake generator used by service tests records its inputs."""
    import asyncio

    fake = FakeBriefGenerator()
    report = sample_report()
    brief = asyncio.run(fake.generate(report, "readme", is_private=False))
    assert brief.summary == "A demo repo."
    assert fake.calls == [(report, "readme", False)]
    assert BriefPoint(text="x", fields=["stars"]).fields == ["stars"]


def test_brief_schema_is_strict() -> None:
    """The json_schema sent to OpenRouter requires all fields, no extras."""
    schema = Brief.model_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    point_schema = schema["$defs"]["BriefPoint"]
    assert point_schema["additionalProperties"] is False
    assert set(point_schema["required"]) == set(point_schema["properties"])


@respx.mock
async def test_call_logged_with_usage_and_no_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The telemetry line carries metrics but never request or reply content."""
    word = "UNIQUE_README_WORD_XYZ_123"
    payload = completion(brief_json())
    payload["id"] = "gen-test-123"
    payload["usage"] = {"prompt_tokens": 111, "completion_tokens": 22, "cost": 0.0015}
    respx.post(URL).respond(200, json=payload)
    generator = await make_generator()
    with caplog.at_level(logging.INFO, logger="app.llm"):
        await generator.generate(sample_report(), f"# Title\n{word}", is_private=False)
    records = [r for r in caplog.records if r.name == "app.llm"]
    assert len(records) == 1
    msg = records[0].getMessage()
    for expected in (
        "model=test/model",
        "result=ok",
        "elapsed=",
        "prompt_tokens=111",
        "completion_tokens=22",
        "cost=0.0015",
        "dropped_points=0",
        "generation_id=gen-test-123",
    ):
        assert expected in msg
    for forbidden in (word, "octo", "A demo repo.", "test-openrouter-key", "untrusted"):
        assert forbidden not in msg
    await generator.aclose()


@respx.mock
async def test_call_logged_on_http_error(caplog: pytest.LogCaptureFixture) -> None:
    """Non-200 replies log the HTTP status as the result."""
    respx.post(URL).respond(500, json={"error": "boom"})
    generator = await make_generator()
    with (
        caplog.at_level(logging.INFO, logger="app.llm"),
        pytest.raises(BriefGenerationError),
    ):
        await generator.generate(sample_report(), None, is_private=False)
    records = [r for r in caplog.records if r.name == "app.llm"]
    assert len(records) == 1
    assert "result=http_500" in records[0].getMessage()
    await generator.aclose()


@respx.mock
async def test_call_logged_on_truncated_reply(caplog: pytest.LogCaptureFixture) -> None:
    """Truncated replies log the result as truncated."""
    respx.post(URL).respond(200, json=completion(brief_json(), "length"))
    generator = await make_generator()
    with (
        caplog.at_level(logging.INFO, logger="app.llm"),
        pytest.raises(BriefGenerationError),
    ):
        await generator.generate(sample_report(), None, is_private=False)
    records = [r for r in caplog.records if r.name == "app.llm"]
    assert len(records) == 1
    assert "result=truncated" in records[0].getMessage()
    await generator.aclose()

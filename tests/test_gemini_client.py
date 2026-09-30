from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest

from media_catalog.gemini_client import (
    GeminiClient,
    GeminiError,
    GeminiSegmentRequest,
)
from media_catalog.inference import Analysis


def _valid_response() -> dict[str, object]:
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "description": "會議畫面顯示季度報表。",
                                    "highlights": ["報表標題清楚"],
                                    "keywords": ["會議", "季度報表"],
                                },
                                ensure_ascii=False,
                            )
                        }
                    ]
                },
                "finishReason": "STOP",
            }
        ]
    }


class RecordingTransport:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.url = ""
        self.headers: dict[str, str] = {}
        self.body: dict[str, object] = {}
        self.timeout = 0.0

    def get(self, url, *, headers, timeout):
        return {"models": [{"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]}]}

    def send(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, object],
        timeout: float,
    ) -> dict[str, object]:
        self.url = url
        self.headers = headers
        self.body = body
        self.timeout = timeout
        return self.response


class FailingTransport:
    def __init__(self, message: str) -> None:
        self.message = message

    def send(self, *_args, **_kwargs):
        raise RuntimeError(self.message)


def _request(tmp_path: Path) -> GeminiSegmentRequest:
    frame = tmp_path / "private-frame.jpg"
    frame.write_bytes(b"preview-bytes")
    return GeminiSegmentRequest(
        frames=(frame,),
        ocr_text="會議標題",
        local_analysis=Analysis("本機描述不足。", ("標題",), ("會議",)),
    )


def test_request_has_preview_bytes_but_no_key_or_local_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-secret")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    transport = RecordingTransport(_valid_response())

    result = GeminiClient(transport=transport).analyze(_request(tmp_path))

    body = json.dumps(transport.body, ensure_ascii=False)
    assert result.description == "會議畫面顯示季度報表。"
    assert "unit-test-secret" not in body
    assert str(tmp_path) not in body
    assert base64.b64encode(b"preview-bytes").decode("ascii") in body
    assert transport.headers["x-goog-api-key"] == "unit-test-secret"
    assert transport.timeout == 90
    assert "/models/gemini-3.8-flash:generateContent" in transport.url


def test_stale_environment_model_cannot_override_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-secret")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-private-preview")
    transport = RecordingTransport(_valid_response())

    GeminiClient(transport=transport).analyze(_request(tmp_path))

    assert "/models/gemini-3.8-flash:generateContent" in transport.url


def test_provider_error_redacts_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-secret")

    with pytest.raises(GeminiError) as captured:
        client = GeminiClient(transport=FailingTransport("unit-test-secret quota payload\nprivate"))
        client.model = "gemini-3.8-flash"
        client.analyze(_request(tmp_path))

    assert "unit-test-secret" not in str(captured.value)
    assert "private" not in str(captured.value)


def test_missing_api_key_fails_before_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(GeminiError, match="GEMINI_API_KEY"):
        GeminiClient(transport=FailingTransport("must not run")).analyze(
            _request(tmp_path)
        )


def test_client_reports_whether_private_environment_key_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = GeminiClient(transport=FailingTransport("must not run"))

    assert client.is_configured is False

    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-secret")
    assert client.is_configured is True


def test_key_check_uses_explicit_key_and_only_lists_models(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'other-key')

    class ListOnlyTransport:
        def __init__(self):
            self.headers = None
            self.calls = 0

        def get(self, url, *, headers, timeout):
            self.calls += 1
            self.headers = headers
            return {'models': [{'name': 'models/gemini-3.8-flash',
                                'supportedGenerationMethods': ['generateContent']}]}

        def send(self, *args, **kwargs):
            raise AssertionError('Key check must not generate content')

    transport = ListOnlyTransport()
    model = GeminiClient(transport=transport).discover_model(key='candidate-key')
    assert model == 'gemini-3.8-flash'
    assert transport.headers == {'x-goog-api-key': 'candidate-key'}
    assert transport.calls == 1
    assert os.environ['GEMINI_API_KEY'] == 'other-key'


def test_malformed_provider_response_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-secret")
    transport = RecordingTransport({"candidates": []})

    with pytest.raises(GeminiError, match="response schema"):
        GeminiClient(transport=transport).analyze(_request(tmp_path))

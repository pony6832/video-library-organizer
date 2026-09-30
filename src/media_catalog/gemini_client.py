from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import urllib.error
import urllib.request
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .inference import Analysis, AnalysisError, LocalAnalyzer


DEFAULT_TIMEOUT_SECONDS = 90.0
_MODEL_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


class GeminiError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GeminiSegmentRequest:
    frames: tuple[Path, ...]
    ocr_text: str
    local_analysis: Analysis


class GeminiTransport(Protocol):
    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> dict[str, object]: ...
    def send(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, object],
        timeout: float,
    ) -> dict[str, object]: ...


class UrllibGeminiTransport:
    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> dict[str, object]:
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"HTTP {error.code}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"network {type(error.reason).__name__}") from error
        except json.JSONDecodeError as error:
            raise RuntimeError("provider returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise RuntimeError("provider returned a non-object response")
        return payload

    def send(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, object],
        timeout: float,
    ) -> dict[str, object]:
        request = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"HTTP {error.code}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"network {type(error.reason).__name__}") from error
        except json.JSONDecodeError as error:
            raise RuntimeError("provider returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise RuntimeError("provider returned a non-object response")
        return payload


class GeminiClient:
    def __init__(
        self,
        *,
        transport: GeminiTransport | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.transport = transport or UrllibGeminiTransport()
        self.timeout_seconds = timeout_seconds
        self.model: str | None = None
        self.discovery_error: str | None = None

    def discover_model(self, *, key: str | None = None) -> str:
        from .model_catalog import select_latest_stable_flash

        key = (os.getenv("GEMINI_API_KEY", "") if key is None else key).strip()
        if not key:
            raise GeminiError("GEMINI_API_KEY is not configured")
        models: list[dict[str, object]] = []
        token = ""
        seen: set[str] = set()
        try:
            while True:
                url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000"
                if token:
                    url += "&pageToken=" + urllib.parse.quote(token, safe="")
                payload = self.transport.get(url, headers={"x-goog-api-key": key}, timeout=self.timeout_seconds)
                page = payload.get("models")
                if not isinstance(page, list):
                    raise GeminiError("Gemini model list response is invalid")
                models.extend(item for item in page if isinstance(item, dict))
                next_token = payload.get("nextPageToken", "")
                if not isinstance(next_token, str):
                    raise GeminiError("Gemini model list page token is invalid")
                if not next_token:
                    break
                if next_token in seen:
                    raise GeminiError("Gemini model list pagination loop")
                seen.add(next_token)
                token = next_token
            self.model = select_latest_stable_flash(models)
            return self.model
        except GeminiError:
            raise
        except Exception as error:
            message = (str(error).splitlines() or [type(error).__name__])[0].replace(key, "[REDACTED]")[:240]
            raise GeminiError(f"Gemini model discovery failed: {message}") from error

    @property
    def is_configured(self) -> bool:
        return bool(os.getenv("GEMINI_API_KEY", "").strip()) and self.discovery_error is None

    def analyze(self, request: GeminiSegmentRequest) -> Analysis:
        key = os.getenv("GEMINI_API_KEY", "").strip()
        if not key:
            raise GeminiError("GEMINI_API_KEY is not configured")
        model = self.model or self.discover_model()
        if _MODEL_NAME.fullmatch(model) is None:
            raise GeminiError("GEMINI_MODEL contains unsupported characters")
        if not 1 <= len(request.frames) <= 3:
            raise GeminiError("Gemini requires one to three preview frames")

        body = self._request_body(request)
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )
        try:
            payload = self.transport.send(
                url,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": key,
                },
                body=body,
                timeout=self.timeout_seconds,
            )
            raw_analysis = self._response_text(payload)
            return LocalAnalyzer._parse_analysis(raw_analysis)
        except GeminiError:
            raise
        except AnalysisError as error:
            raise GeminiError("Gemini response schema is invalid") from error
        except Exception as error:
            message = str(error).splitlines()[0] if str(error) else type(error).__name__
            redacted = message.replace(key, "[REDACTED]")[:240]
            raise GeminiError(f"Gemini request failed: {redacted}") from error

    @staticmethod
    def _request_body(request: GeminiSegmentRequest) -> dict[str, object]:
        local_summary = json.dumps(
            {
                "description": request.local_analysis.description,
                "highlights": request.local_analysis.highlights,
                "keywords": request.local_analysis.keywords,
            },
            ensure_ascii=False,
        )
        prompt = (
            "請根據縮圖、OCR 與本機初步摘要補強分析。只輸出單一 JSON 物件，"
            "欄位固定為 description、highlights、keywords；內容使用繁體中文，"
            "三個欄位都不得空白。OCR："
            f"{request.ocr_text}\n本機摘要：{local_summary}"
        )
        parts: list[dict[str, object]] = [{"text": prompt}]
        for frame in request.frames:
            path = Path(frame)
            if not path.is_file():
                raise GeminiError("Gemini preview frame is missing")
            mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
            if not mime_type.startswith("image/"):
                raise GeminiError("Gemini preview must be an image")
            parts.append(
                {
                    "inline_data": {
                        "mime_type": mime_type,
                        "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                    }
                }
            )
        return {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseMimeType": "application/json"},
        }

    @staticmethod
    def _response_text(payload: dict[str, object]) -> str:
        try:
            candidates = payload["candidates"]
            candidate = candidates[0]
            parts = candidate["content"]["parts"]
            text = next(
                part["text"]
                for part in parts
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            )
        except (KeyError, IndexError, StopIteration, TypeError) as error:
            raise GeminiError("Gemini response schema is invalid") from error
        return text

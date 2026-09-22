from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from .gemini_client import GeminiError


_STABLE_FLASH = re.compile(r"(?:models/)?(gemini-(\d+)(?:\.(\d+))?-flash(?:-(\d{3}))?)$", re.IGNORECASE)


def select_latest_stable_flash(models: Iterable[Mapping[str, object]]) -> str:
    """Select a general, formally named Flash model supporting generateContent."""
    candidates: list[tuple[int, int, int, str]] = []
    for model in models:
        name = model.get("name")
        methods = model.get("supportedGenerationMethods")
        if not isinstance(name, str) or not isinstance(methods, list):
            continue
        match = _STABLE_FLASH.fullmatch(name)
        if match and "generateContent" in methods:
            candidates.append((int(match[2]), int(match[3] or 0), int(match[4] or 0), match[1].lower()))
    if not candidates:
        raise GeminiError("No stable general Gemini Flash model is available; check model access.")
    return max(candidates)[3]

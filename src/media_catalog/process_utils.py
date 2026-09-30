from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping


HIDDEN_PROCESS_CREATION_FLAGS = getattr(
    subprocess, "CREATE_NO_WINDOW", 0
)

# Provider credentials that must never reach third-party tools (ffmpeg, npm
# lifecycle scripts, winget installers, Ollama, watch/MCP helpers).
CREDENTIAL_ENVIRONMENT_KEYS = (
    "OPENAI_API_KEY",
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "TWELVELABS_API_KEY",
)


def credential_free_environment(
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    environment = dict(os.environ if base is None else base)
    for key in CREDENTIAL_ENVIRONMENT_KEYS:
        environment.pop(key, None)
    return environment

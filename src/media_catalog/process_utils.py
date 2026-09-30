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


def _kill_process_tree(process: subprocess.Popen) -> None:
    """Kill a child *and its descendants*.

    ``subprocess.run(timeout=...)`` and ``Popen.terminate()`` only stop the
    direct child; on Windows the ffmpeg/node processes started by a ``.cmd``
    wrapper or helper script keep running (and holding files) afterwards.
    """
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
                creationflags=HIDDEN_PROCESS_CREATION_FLAGS,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    if process.poll() is None:
        process.kill()


def terminate_process_tree(process) -> None:
    """Stop a worker; real ``Popen`` objects lose their whole process tree."""
    if isinstance(process, subprocess.Popen):
        if process.poll() is None:
            _kill_process_tree(process)
        return
    process.terminate()


def run_process_tree(
    args,
    *,
    timeout: float | None = None,
    capture_output: bool = False,
    check: bool = False,
    input=None,
    **popen_kwargs,
) -> subprocess.CompletedProcess:
    """``subprocess.run`` look-alike that kills the process tree on timeout."""
    if capture_output:
        popen_kwargs.setdefault("stdout", subprocess.PIPE)
        popen_kwargs.setdefault("stderr", subprocess.PIPE)
    if input is not None:
        popen_kwargs.setdefault("stdin", subprocess.PIPE)
    else:
        popen_kwargs.setdefault("stdin", subprocess.DEVNULL)
    with subprocess.Popen(args, **popen_kwargs) as process:
        try:
            stdout, stderr = process.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_process_tree(process)
            try:
                stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                stdout = stderr = None
            raise subprocess.TimeoutExpired(
                args, timeout, output=stdout, stderr=stderr
            ) from None
        except BaseException:
            _kill_process_tree(process)
            raise
        returncode = process.poll()
    if check and returncode:
        raise subprocess.CalledProcessError(
            returncode, args, output=stdout, stderr=stderr
        )
    return subprocess.CompletedProcess(args, returncode, stdout, stderr)

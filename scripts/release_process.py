#!/usr/bin/env python3
"""Run release subprocesses inside a bounded, credential-free process group.

Release helpers execute reviewed tools, but those tools can still hang, fork,
ignore cancellation, emit unbounded output, or accidentally inherit publisher
credentials.  This module is the single process boundary for release scripts:
every invocation gets a fresh process group and sterile home, bounded output,
an absolute deadline, and group-wide TERM/KILL cleanup.
"""

from __future__ import annotations

import math
import os
import selectors
import signal
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Any, Iterator, Mapping, NoReturn, Sequence

DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_OUTPUT_LIMIT_BYTES = 2 * 1024 * 1024
DEFAULT_TERMINATION_GRACE_SECONDS = 0.5
DEFAULT_KILL_WAIT_SECONDS = 2.0
_READ_CHUNK_BYTES = 64 * 1024
_POLL_INTERVAL_SECONDS = 0.02
_SAFE_INHERITED_ENVIRONMENT = frozenset(
    {
        "LANG",
        "LC_ALL",
        "PATH",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "TEMP",
        "TMP",
        "TMPDIR",
        "TZ",
        "VIRTUAL_ENV",
    }
)
_SAFE_ENVIRONMENT_OVERRIDES = _SAFE_INHERITED_ENVIRONMENT | frozenset(
    {
        "PYTHONHASHSEED",
        "SOURCE_DATE_EPOCH",
    }
)


@dataclass(frozen=True)
class ReleaseProcessResult:
    """The complete bounded result of one contained process group."""

    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class ReleaseProcessError(RuntimeError):
    """A contained process violated a release execution invariant."""

    def __init__(
        self,
        message: str,
        *,
        command: Sequence[str],
        stdout: bytes = b"",
        stderr: bytes = b"",
    ) -> None:
        self.command = tuple(command)
        self.stdout = stdout.decode("utf-8", "replace")
        self.stderr = stderr.decode("utf-8", "replace")
        detail = self.stderr.strip() or self.stdout.strip()
        if len(detail) > 4096:
            detail = f"{detail[:4096]}…"
        suffix = f": {detail}" if detail else ""
        super().__init__(f"{message}{suffix}")


class _ReleaseProcessInterruption(BaseException):
    def __init__(self, signal_number: int) -> None:
        self.signal_number = signal_number
        super().__init__(signal_number)


@contextmanager
def _termination_signals_as_exceptions() -> Iterator[None]:
    watched_signals = (signal.SIGHUP, signal.SIGTERM)
    previous_handlers: dict[signal.Signals, Any] = {}

    def interrupt(signal_number: int, frame: FrameType | None) -> NoReturn:
        del frame
        for watched_signal in watched_signals:
            signal.signal(watched_signal, signal.SIG_IGN)
        raise _ReleaseProcessInterruption(signal_number)

    for watched_signal in watched_signals:
        previous_handlers[watched_signal] = signal.getsignal(watched_signal)
        signal.signal(watched_signal, interrupt)
    try:
        yield
    finally:
        for watched_signal, previous_handler in previous_handlers.items():
            signal.signal(watched_signal, previous_handler)


def _positive_number(value: float, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{field} must be a finite positive number")
    return float(value)


def _positive_integer(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _sanitized_environment(
    overrides: Mapping[str, str] | None,
    *,
    sterile_home: Path,
) -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if key in _SAFE_INHERITED_ENVIRONMENT
    }
    environment.setdefault("PATH", os.defpath)
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "HOME": str(sterile_home),
            "NPM_CONFIG_USERCONFIG": os.devnull,
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONNOUSERSITE": "1",
            "TWINE_CONFIG_FILE": os.devnull,
            "UV_NO_CONFIG": "1",
            "XDG_CACHE_HOME": str(sterile_home / ".cache"),
            "XDG_CONFIG_HOME": str(sterile_home / ".config"),
        }
    )
    for key, value in (overrides or {}).items():
        if key not in _SAFE_ENVIRONMENT_OVERRIDES:
            raise ValueError(f"release subprocess environment override is not allowed: {key}")
        if not isinstance(value, str) or "\x00" in value:
            raise ValueError(f"release subprocess environment value is invalid: {key}")
        environment[key] = value
    return environment


def _group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _signal_group(process_group_id: int, signal_number: int) -> None:
    try:
        os.killpg(process_group_id, signal_number)
    except ProcessLookupError:
        return


def _append_bounded(target: bytearray, payload: bytes, limit: int) -> bool:
    remaining = max(0, limit - len(target))
    if remaining:
        target.extend(payload[:remaining])
    return len(payload) > remaining


def _read_ready_streams(
    selector: selectors.BaseSelector,
    outputs: dict[str, bytearray],
    *,
    output_limit_bytes: int,
    wait_seconds: float,
) -> set[str]:
    exceeded: set[str] = set()
    events = selector.select(max(0.0, wait_seconds))
    for key, _mask in events:
        stream_name = str(key.data)
        try:
            payload = os.read(key.fd, _READ_CHUNK_BYTES)
        except BlockingIOError:
            continue
        if not payload:
            selector.unregister(key.fileobj)
            continue
        if _append_bounded(outputs[stream_name], payload, output_limit_bytes):
            exceeded.add(stream_name)
    return exceeded


def _wait_for_group_exit(
    process: subprocess.Popen[bytes],
    process_group_id: int,
    selector: selectors.BaseSelector,
    outputs: dict[str, bytearray],
    *,
    output_limit_bytes: int,
    deadline: float,
) -> bool:
    while True:
        process.poll()
        if not _group_exists(process_group_id):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        _read_ready_streams(
            selector,
            outputs,
            output_limit_bytes=output_limit_bytes,
            wait_seconds=min(_POLL_INTERVAL_SECONDS, remaining),
        )


def _drain_closed_streams(
    selector: selectors.BaseSelector,
    outputs: dict[str, bytearray],
    *,
    output_limit_bytes: int,
    deadline: float,
) -> None:
    while selector.get_map():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        _read_ready_streams(
            selector,
            outputs,
            output_limit_bytes=output_limit_bytes,
            wait_seconds=min(_POLL_INTERVAL_SECONDS, remaining),
        )


def _terminate_process_group(
    process: subprocess.Popen[bytes],
    process_group_id: int,
    selector: selectors.BaseSelector,
    outputs: dict[str, bytearray],
    *,
    output_limit_bytes: int,
    termination_grace_seconds: float,
    kill_wait_seconds: float,
) -> bool:
    if _group_exists(process_group_id):
        _signal_group(process_group_id, signal.SIGTERM)
        terminated = _wait_for_group_exit(
            process,
            process_group_id,
            selector,
            outputs,
            output_limit_bytes=output_limit_bytes,
            deadline=time.monotonic() + termination_grace_seconds,
        )
        if not terminated:
            _signal_group(process_group_id, signal.SIGKILL)
            _wait_for_group_exit(
                process,
                process_group_id,
                selector,
                outputs,
                output_limit_bytes=output_limit_bytes,
                deadline=time.monotonic() + kill_wait_seconds,
            )
    process.poll()
    _drain_closed_streams(
        selector,
        outputs,
        output_limit_bytes=output_limit_bytes,
        deadline=time.monotonic() + min(kill_wait_seconds, 0.5),
    )
    try:
        process.wait(timeout=max(0.01, min(kill_wait_seconds, 0.5)))
    except subprocess.TimeoutExpired:
        _signal_group(process_group_id, signal.SIGKILL)
        try:
            process.wait(timeout=max(0.01, min(kill_wait_seconds, 0.5)))
        except subprocess.TimeoutExpired:
            return False
    return not _group_exists(process_group_id)


def _raise_process_error(
    message: str,
    *,
    command: Sequence[str],
    outputs: dict[str, bytearray],
) -> NoReturn:
    raise ReleaseProcessError(
        message,
        command=command,
        stdout=bytes(outputs["stdout"]),
        stderr=bytes(outputs["stderr"]),
    )


def _run_release_process(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    output_limit_bytes: int = DEFAULT_OUTPUT_LIMIT_BYTES,
    termination_grace_seconds: float = DEFAULT_TERMINATION_GRACE_SECONDS,
    kill_wait_seconds: float = DEFAULT_KILL_WAIT_SECONDS,
) -> ReleaseProcessResult:
    """Run one command with bounded output, lifetime, descendants, and environment."""

    if os.name != "posix":
        raise ReleaseProcessError(
            "release subprocess containment requires a POSIX runner",
            command=command,
        )
    if not command or any(
        not isinstance(argument, str) or "\x00" in argument for argument in command
    ):
        raise ValueError("release subprocess command must contain valid strings")
    timeout_seconds = _positive_number(timeout_seconds, "timeout_seconds")
    termination_grace_seconds = _positive_number(
        termination_grace_seconds,
        "termination_grace_seconds",
    )
    kill_wait_seconds = _positive_number(kill_wait_seconds, "kill_wait_seconds")
    output_limit_bytes = _positive_integer(output_limit_bytes, "output_limit_bytes")
    absolute_deadline = time.monotonic() + timeout_seconds
    outputs = {"stdout": bytearray(), "stderr": bytearray()}

    with tempfile.TemporaryDirectory(prefix="videovector-release-process-") as home:
        child_environment = _sanitized_environment(env, sterile_home=Path(home))
        selector = selectors.DefaultSelector()
        try:
            process = subprocess.Popen(
                list(command),
                cwd=cwd,
                env=child_environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
                restore_signals=True,
                text=False,
                bufsize=0,
            )
        except OSError as error:
            selector.close()
            raise ReleaseProcessError(
                f"cannot start release subprocess: {error}",
                command=command,
            ) from error

        process_group_id = process.pid
        failure: str | None = None
        cleanup_returned = False
        try:
            assert process.stdout is not None
            assert process.stderr is not None
            for stream_name, stream in (
                ("stdout", process.stdout),
                ("stderr", process.stderr),
            ):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, stream_name)

            while True:
                remaining = absolute_deadline - time.monotonic()
                if remaining <= 0:
                    failure = f"release subprocess exceeded its {timeout_seconds:g}s deadline"
                    break
                exceeded = _read_ready_streams(
                    selector,
                    outputs,
                    output_limit_bytes=output_limit_bytes,
                    wait_seconds=min(_POLL_INTERVAL_SECONDS, remaining),
                )
                if exceeded:
                    streams = " and ".join(sorted(exceeded))
                    failure = (
                        f"release subprocess {streams} exceeded " f"{output_limit_bytes} bytes"
                    )
                    break

                returncode = process.poll()
                if returncode is None:
                    continue
                if _group_exists(process_group_id):
                    failure = "release subprocess exited while descendants remained"
                    break
                if selector.get_map():
                    continue
                return ReleaseProcessResult(
                    command=tuple(command),
                    returncode=returncode,
                    stdout=bytes(outputs["stdout"]).decode("utf-8", "replace"),
                    stderr=bytes(outputs["stderr"]).decode("utf-8", "replace"),
                )

            cleaned = _terminate_process_group(
                process,
                process_group_id,
                selector,
                outputs,
                output_limit_bytes=output_limit_bytes,
                termination_grace_seconds=termination_grace_seconds,
                kill_wait_seconds=kill_wait_seconds,
            )
            cleanup_returned = True
            if not cleaned:
                failure = f"{failure}; process group did not settle after SIGKILL"
            _raise_process_error(
                failure,
                command=command,
                outputs=outputs,
            )
        except BaseException:
            if not cleanup_returned:
                _terminate_process_group(
                    process,
                    process_group_id,
                    selector,
                    outputs,
                    output_limit_bytes=output_limit_bytes,
                    termination_grace_seconds=termination_grace_seconds,
                    kill_wait_seconds=kill_wait_seconds,
                )
            raise
        finally:
            selector.close()
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()


def run_release_process(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    output_limit_bytes: int = DEFAULT_OUTPUT_LIMIT_BYTES,
    termination_grace_seconds: float = DEFAULT_TERMINATION_GRACE_SECONDS,
    kill_wait_seconds: float = DEFAULT_KILL_WAIT_SECONDS,
) -> ReleaseProcessResult:
    """Run one command and settle its process group before returning or failing."""

    if threading.current_thread() is not threading.main_thread():
        raise ReleaseProcessError(
            "release subprocess containment must run on the main thread",
            command=command,
        )
    try:
        with _termination_signals_as_exceptions():
            return _run_release_process(
                command,
                cwd=cwd,
                env=env,
                timeout_seconds=timeout_seconds,
                output_limit_bytes=output_limit_bytes,
                termination_grace_seconds=termination_grace_seconds,
                kill_wait_seconds=kill_wait_seconds,
            )
    except _ReleaseProcessInterruption as interruption:
        signal_name = signal.Signals(interruption.signal_number).name
        raise ReleaseProcessError(
            f"release subprocess runner interrupted by {signal_name}",
            command=command,
        ) from interruption

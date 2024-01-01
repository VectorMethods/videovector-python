from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts import release_process


def _process_is_live(process_id: int) -> bool:
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    status_path = Path(f"/proc/{process_id}/stat")
    if status_path.is_file():
        try:
            return status_path.read_text(encoding="utf-8").split()[2] != "Z"
        except (OSError, IndexError):
            pass
    return True


def _assert_processes_settle(process_ids: list[int]) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and any(
        _process_is_live(process_id) for process_id in process_ids
    ):
        time.sleep(0.02)
    assert all(not _process_is_live(process_id) for process_id in process_ids)


def test_runner_sanitizes_environment_and_closes_inherited_descriptors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    inherited_credentials = {
        "AWS_SECRET_ACCESS_KEY": "aws-secret",
        "GITHUB_TOKEN": "github-secret",
        "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/google-secret.json",
        "NPM_TOKEN": "npm-secret",
        "PYTHONPATH": "/tmp/unreviewed-code",
        "TWINE_PASSWORD": "twine-secret",
    }
    for name, value in inherited_credentials.items():
        monkeypatch.setenv(name, value)
    parent_home = str(tmp_path / "credential-bearing-home")
    monkeypatch.setenv("HOME", parent_home)

    descriptor = os.open(tmp_path / "credential", os.O_CREAT | os.O_RDWR, 0o600)
    os.set_inheritable(descriptor, True)
    try:
        code = """
import json
import os
import sys

try:
    os.fstat(int(sys.argv[1]))
except OSError:
    descriptor_open = False
else:
    descriptor_open = True
names = sys.argv[2:]
print(json.dumps({
    "descriptor_open": descriptor_open,
    "environment": {name: os.environ.get(name) for name in names},
    "home": os.environ.get("HOME"),
    "path": os.environ.get("PATH"),
    "source_date_epoch": os.environ.get("SOURCE_DATE_EPOCH"),
}))
print("bounded stderr", file=sys.stderr)
"""
        result = release_process.run_release_process(
            (sys.executable, "-c", code, str(descriptor), *inherited_credentials),
            cwd=tmp_path,
            env={"LC_ALL": "C", "SOURCE_DATE_EPOCH": "1700000000"},
            timeout_seconds=2,
        )
    finally:
        os.close(descriptor)

    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert result.stderr == "bounded stderr\n"
    assert payload["descriptor_open"] is False
    assert payload["environment"] == {name: None for name in inherited_credentials}
    assert payload["home"] != parent_home
    assert not Path(payload["home"]).exists()
    assert payload["path"]
    assert payload["source_date_epoch"] == "1700000000"


def test_runner_rejects_credential_environment_override(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not allowed: GITHUB_TOKEN"):
        release_process.run_release_process(
            (sys.executable, "-c", "pass"),
            cwd=tmp_path,
            env={"GITHUB_TOKEN": "must-not-cross-boundary"},
        )


@pytest.mark.parametrize("timeout_seconds", (True, 0, -1, float("inf"), float("nan")))
def test_runner_rejects_non_finite_or_nonpositive_deadline(
    timeout_seconds: float,
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="finite positive"):
        release_process.run_release_process(
            (sys.executable, "-c", "pass"),
            cwd=tmp_path,
            timeout_seconds=timeout_seconds,
        )


@pytest.mark.parametrize(("stream", "descriptor"), (("stdout", 1), ("stderr", 2)))
def test_runner_enforces_each_stream_output_bound(
    stream: str,
    descriptor: int,
    tmp_path: Path,
) -> None:
    with pytest.raises(
        release_process.ReleaseProcessError,
        match=rf"{stream} exceeded 256 bytes",
    ) as captured:
        release_process.run_release_process(
            (
                sys.executable,
                "-c",
                "import os, sys; os.write(int(sys.argv[1]), b'x' * 4096)",
                str(descriptor),
            ),
            cwd=tmp_path,
            timeout_seconds=2,
            output_limit_bytes=256,
            termination_grace_seconds=0.05,
            kill_wait_seconds=1,
        )

    assert len(captured.value.stdout.encode()) <= 256
    assert len(captured.value.stderr.encode()) <= 256


def test_runner_deadline_kills_term_resistant_parent_and_child(tmp_path: Path) -> None:
    process_ids = tmp_path / "process-ids"
    code = """
import os
import signal
import subprocess
import sys
import time

signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = subprocess.Popen([
    sys.executable,
    "-c",
    "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)",
])
with open(sys.argv[1], "w", encoding="utf-8") as target:
    target.write(f"{os.getpid()} {child.pid}")
    target.flush()
while True:
    time.sleep(1)
"""
    started = time.monotonic()
    with pytest.raises(release_process.ReleaseProcessError, match="deadline"):
        release_process.run_release_process(
            (sys.executable, "-c", code, str(process_ids)),
            cwd=tmp_path,
            timeout_seconds=0.25,
            output_limit_bytes=1024,
            termination_grace_seconds=0.1,
            kill_wait_seconds=1.5,
        )
    elapsed = time.monotonic() - started

    assert elapsed < 3
    killed_process_ids = [int(value) for value in process_ids.read_text().split()]
    _assert_processes_settle(killed_process_ids)


def test_runner_kills_descendant_when_direct_parent_exits(tmp_path: Path) -> None:
    child_id = tmp_path / "child-id"
    code = """
import subprocess
import sys

child = subprocess.Popen([
    sys.executable,
    "-c",
    "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)",
])
with open(sys.argv[1], "w", encoding="utf-8") as target:
    target.write(str(child.pid))
    target.flush()
"""
    with pytest.raises(
        release_process.ReleaseProcessError,
        match="exited while descendants remained",
    ):
        release_process.run_release_process(
            (sys.executable, "-c", code, str(child_id)),
            cwd=tmp_path,
            timeout_seconds=2,
            output_limit_bytes=1024,
            termination_grace_seconds=0.05,
            kill_wait_seconds=1.5,
        )

    _assert_processes_settle([int(child_id.read_text())])


def test_runner_deadline_is_absolute_despite_output_activity(tmp_path: Path) -> None:
    code = """
import sys
import time

while True:
    print("activity", flush=True)
    print("activity", file=sys.stderr, flush=True)
    time.sleep(0.01)
"""
    started = time.monotonic()
    with pytest.raises(release_process.ReleaseProcessError, match="deadline"):
        release_process.run_release_process(
            (sys.executable, "-c", code),
            cwd=tmp_path,
            timeout_seconds=0.2,
            output_limit_bytes=64 * 1024,
            termination_grace_seconds=0.05,
            kill_wait_seconds=1,
        )

    assert time.monotonic() - started < 1.5


def test_runner_settles_child_group_before_external_sigterm_exit(tmp_path: Path) -> None:
    child_id = tmp_path / "externally-interrupted-child"
    repository = Path(__file__).parents[1]
    child_code = """
import os
import signal
import sys
import time

signal.signal(signal.SIGTERM, signal.SIG_IGN)
with open(sys.argv[1], "w", encoding="utf-8") as target:
    target.write(str(os.getpid()))
    target.flush()
while True:
    time.sleep(1)
"""
    harness_code = """
import sys
from pathlib import Path
from scripts.release_process import run_release_process

run_release_process(
    (sys.executable, "-c", sys.argv[3], sys.argv[1]),
    cwd=Path(sys.argv[2]),
    timeout_seconds=60,
    output_limit_bytes=1024,
    termination_grace_seconds=0.05,
    kill_wait_seconds=1.5,
)
"""
    harness = subprocess.Popen(
        (
            sys.executable,
            "-c",
            harness_code,
            str(child_id),
            str(repository),
            child_code,
        ),
        cwd=repository,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    child_process_id: int | None = None
    try:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not child_id.exists() and harness.poll() is None:
            time.sleep(0.02)
        assert child_id.exists()
        child_process_id = int(child_id.read_text())

        harness.terminate()
        _stdout, stderr = harness.communicate(timeout=4)

        assert harness.returncode != 0
        assert "interrupted by SIGTERM" in stderr
        _assert_processes_settle([child_process_id])
    finally:
        if harness.poll() is None:
            os.killpg(harness.pid, signal.SIGKILL)
            harness.wait(timeout=2)
        if child_process_id is not None and _process_is_live(child_process_id):
            os.kill(child_process_id, signal.SIGKILL)


def test_runner_returns_nonzero_result_without_losing_stderr(tmp_path: Path) -> None:
    result = release_process.run_release_process(
        (
            sys.executable,
            "-c",
            "import sys; print('failure detail', file=sys.stderr); raise SystemExit(7)",
        ),
        cwd=tmp_path,
        timeout_seconds=2,
    )

    assert result.returncode == 7
    assert result.stdout == ""
    assert result.stderr == "failure detail\n"

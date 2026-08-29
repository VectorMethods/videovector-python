#!/usr/bin/env python3
"""Build, attest, and verify one immutable Python release bundle.

The release bundle is intentionally separate from registry publication. A
successful build produces the wheel and sdist exactly once, normalizes archive
timestamps, and records every byte in ``release-manifest.json``. Publication
jobs consume that bundle and use ``registry-status`` to distinguish a missing
version from an exact replay or a conflicting pre-existing version.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import copy
import csv
import gzip
import hashlib
import importlib
import json
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from email.parser import BytesParser
from http.client import HTTPMessage
from importlib import metadata as importlib_metadata
from pathlib import Path, PurePosixPath
from typing import IO, Any, Mapping, NoReturn, Sequence, cast

if __package__ in {None, ""}:  # Support direct ``python scripts/...`` execution.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.release_process import ReleaseProcessError, run_release_process

SCHEMA_VERSION = "1.1.0"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_REGISTRY_URLS = {
    "pypi": "https://pypi.org",
    "testpypi": "https://test.pypi.org",
}
DEFAULT_REPOSITORY = "VectorMethods/videovector-python"
DEFAULT_PACKAGE = "videovector"
EXPECTED_TOOL_VERSIONS = {
    "python": "3.11.13",
    "build": "1.4.4",
    "setuptools": "80.10.2",
    "twine": "6.2.0",
    "uv": "0.11.29",
    "wheel": "0.47.0",
}
STABLE_VERSION_PATTERN = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
MAX_CONTROL_FILE_BYTES = 2 * 1024 * 1024
MAX_REGISTRY_METADATA_BYTES = MAX_CONTROL_FILE_BYTES
MAX_WHEEL_BYTES = 128 * 1024 * 1024
MAX_SDIST_BYTES = 256 * 1024 * 1024
MAX_DISTRIBUTION_ENTRIES = 20_000
MAX_EXPANDED_DISTRIBUTION_BYTES = 2 * 1024 * 1024 * 1024
TRUSTED_DISTRIBUTION_HOSTS = {
    "pypi": frozenset({"files.pythonhosted.org"}),
    "testpypi": frozenset({"files.pythonhosted.org", "test-files.pythonhosted.org"}),
}


class ReleaseArtifactError(RuntimeError):
    """Release bundle or registry state is unsafe."""


_FORBIDDEN_CREDENTIAL_BASENAMES = frozenset(
    {
        ".env",
        ".git-credentials",
        ".netrc",
        ".npmrc",
        ".pypirc",
        "credentials",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
        "kubeconfig",
        "secrets",
    }
)
_FORBIDDEN_CREDENTIAL_PATHS = frozenset({".aws/credentials", ".docker/config.json"})
_FORBIDDEN_CREDENTIAL_PATTERNS = (
    re.compile(r"^client[-_]?secret.*\.json(?:[._~-].*)?$", re.IGNORECASE),
    re.compile(r"^gha-creds-[a-z0-9._-]*\.json(?:[._~-].*)?$", re.IGNORECASE),
    re.compile(r".*firebase-adminsdk.*\.json(?:[._~-].*)?$", re.IGNORECASE),
    re.compile(r".*(?:credential|credentials).*\.json(?:[._~-].*)?$", re.IGNORECASE),
    re.compile(r".*service[-_]?account.*\.json(?:[._~-].*)?$", re.IGNORECASE),
    re.compile(r".*\.(?:key|p12|pem|pfx)(?:[._~-].*)?$", re.IGNORECASE),
)
_SAFE_CREDENTIAL_EXAMPLE_MARKERS = frozenset({"example", "sample", "schema", "template"})
_SAFE_CREDENTIAL_EXAMPLE_EXTENSIONS = frozenset(
    {"cfg", "conf", "ini", "json", "key", "p12", "pem", "pfx", "toml", "txt", "yaml", "yml"}
)


def _is_forbidden_credential_path(raw_path: str) -> bool:
    path = PurePosixPath(raw_path.replace("\\", "/"))
    normalized = path.as_posix().casefold().removeprefix("./")
    basename = path.name.casefold()
    segments = [segment for segment in basename.split(".") if segment]
    if (
        basename.startswith(".env.")
        and basename.removeprefix(".env.") in _SAFE_CREDENTIAL_EXAMPLE_MARKERS
        or segments
        and segments[-1] in _SAFE_CREDENTIAL_EXAMPLE_MARKERS
        or len(segments) >= 2
        and segments[-2] in _SAFE_CREDENTIAL_EXAMPLE_MARKERS
        and segments[-1] in _SAFE_CREDENTIAL_EXAMPLE_EXTENSIONS
    ):
        return False

    def matches_family(value: str, family: str) -> bool:
        if value == family:
            return True
        return (
            value.startswith(family)
            and len(value) > len(family)
            and value[len(family)] in ".-_~"
            and not (family.startswith("id_") and value[len(family) :] == ".pub")
        )

    def matches_path_family(value: str, family: str) -> bool:
        start = value.rfind(family)
        if start < 0 or start > 0 and value[start - 1] != "/":
            return False
        return matches_family(value[start:], family)

    if any(matches_path_family(normalized, forbidden) for forbidden in _FORBIDDEN_CREDENTIAL_PATHS):
        return True
    if any(matches_family(basename, forbidden) for forbidden in _FORBIDDEN_CREDENTIAL_BASENAMES):
        return True
    if basename.startswith(".env."):
        return True
    return any(pattern.fullmatch(path.name) for pattern in _FORBIDDEN_CREDENTIAL_PATTERNS)


def _require_https_url(url: str, allowed_hosts: frozenset[str], field: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.hostname.lower() not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ReleaseArtifactError(f"{field} is not a trusted HTTPS URL")
    return url


class _StrictRegistryRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts: frozenset[str]) -> None:
        super().__init__()
        self._allowed_hosts = allowed_hosts

    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: IO[bytes],
        code: int,
        message: str,
        headers: HTTPMessage,
        new_url: str,
    ) -> urllib.request.Request | None:
        _require_https_url(new_url, self._allowed_hosts, "registry redirect")
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )


def _open_registry_url(
    url: str,
    *,
    timeout: float,
    allowed_hosts: frozenset[str],
) -> Any:
    _require_https_url(url, allowed_hosts, "registry URL")
    opener = urllib.request.build_opener(_StrictRegistryRedirectHandler(allowed_hosts))
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "videovector-release-verifier/1"},
    )
    response = opener.open(request, timeout=timeout)
    final_url_getter = getattr(response, "geturl", None)
    final_url = final_url_getter() if callable(final_url_getter) else url
    _require_https_url(str(final_url), allowed_hosts, "registry response URL")
    return response


def _read_bounded_response(response: Any, *, max_bytes: int, field: str) -> bytes:
    content_length = response.headers.get("Content-Length") if response.headers else None
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except (TypeError, ValueError) as error:
            raise ReleaseArtifactError(f"{field} has an invalid Content-Length") from error
        if declared_length < 0 or declared_length > max_bytes:
            raise ReleaseArtifactError(f"{field} exceeds its byte limit")
    payload = response.read(max_bytes + 1)
    if not isinstance(payload, bytes):
        raise ReleaseArtifactError(f"{field} did not return bytes")
    if len(payload) > max_bytes:
        raise ReleaseArtifactError(f"{field} exceeds its byte limit")
    return payload


def _stream_registry_artifact(
    response: Any,
    *,
    destination: Path,
    expected_size: int,
    expected_sha256: str,
    field: str,
) -> None:
    content_length = response.headers.get("Content-Length") if response.headers else None
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except (TypeError, ValueError) as error:
            raise ReleaseArtifactError(f"{field} has an invalid Content-Length") from error
        if declared_length != expected_size:
            raise ReleaseArtifactError(f"{field} Content-Length differs")
    digest = hashlib.sha256()
    observed_size = 0
    try:
        with destination.open("xb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                observed_size += len(chunk)
                if observed_size > expected_size:
                    raise ReleaseArtifactError(f"{field} exceeds its declared size")
                digest.update(chunk)
                output.write(chunk)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    if observed_size != expected_size or digest.hexdigest() != expected_sha256:
        destination.unlink(missing_ok=True)
        raise ReleaseArtifactError(f"{field} bytes differ")


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    capture: bool = False,
    timeout_seconds: float = 30.0,
) -> str:
    completed = run_release_process(
        command,
        cwd=cwd,
        env=env,
        timeout_seconds=timeout_seconds,
    )
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(
            completed.returncode,
            completed.command,
            output=completed.stdout,
            stderr=completed.stderr,
        )
    if capture:
        return completed.stdout.strip()
    if completed.stdout:
        print(completed.stdout, end="", file=sys.stdout)
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    return ""


def _git(root: Path, *arguments: str) -> str:
    return _run(("git", *arguments), cwd=root, capture=True)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(_stable_json_bytes(value))


def _require_sha256(value: str, field: str) -> str:
    normalized = value.strip().lower()
    if not SHA256_PATTERN.fullmatch(normalized):
        raise ReleaseArtifactError(f"{field} must be a lowercase SHA-256 digest")
    return normalized


def _safe_archive_path(raw_path: str, *, field: str) -> str:
    path = raw_path.rstrip("/")
    relative = PurePosixPath(path)
    if (
        not path
        or raw_path.startswith("/")
        or "\\" in raw_path
        or "\x00" in raw_path
        or str(relative) != path
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ReleaseArtifactError(f"{field} contains an unsafe path: {raw_path}")
    return path


def _fixed_zip_datetime(epoch: int) -> tuple[int, int, int, int, int, int]:
    # ZIP cannot represent dates before 1980. Release commits are newer, but
    # clamping makes the normalizer total for synthetic tests.
    import datetime

    moment = datetime.datetime.fromtimestamp(max(epoch, 315532800), datetime.timezone.utc)
    return (
        moment.year,
        moment.month,
        moment.day,
        moment.hour,
        moment.minute,
        moment.second - (moment.second % 2),
    )


def normalize_wheel(path: Path, epoch: int) -> None:
    """Rewrite ZIP metadata without changing wheel file contents."""
    target = path.with_suffix(f"{path.suffix}.normalized")
    fixed_time = _fixed_zip_datetime(epoch)
    with (
        zipfile.ZipFile(path, "r") as source,
        zipfile.ZipFile(
            target,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            strict_timestamps=True,
        ) as destination,
    ):
        for current in sorted(source.infolist(), key=lambda item: item.filename):
            payload = source.read(current)
            normalized = zipfile.ZipInfo(current.filename, fixed_time)
            normalized.compress_type = current.compress_type
            normalized.create_system = 3
            normalized.external_attr = (
                (stat.S_IFDIR | 0o755) if current.is_dir() else (stat.S_IFREG | 0o644)
            ) << 16
            normalized.internal_attr = 0
            normalized.flag_bits = current.flag_bits & 0x800
            destination.writestr(
                normalized,
                payload,
                compress_type=current.compress_type,
                compresslevel=9,
            )
    target.replace(path)


def normalize_sdist(path: Path, epoch: int) -> None:
    """Rewrite tar and gzip metadata to a commit-derived timestamp."""
    target = path.with_suffix(f"{path.suffix}.normalized")
    with tarfile.open(path, "r:gz") as source, target.open("wb") as raw_output:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw_output,
            compresslevel=9,
            mtime=epoch,
        ) as gzip_output:
            with tarfile.open(
                fileobj=cast(IO[bytes], gzip_output),
                mode="w",
                format=tarfile.PAX_FORMAT,
            ) as destination:
                for current in sorted(source.getmembers(), key=lambda item: item.name):
                    normalized = copy.copy(current)
                    normalized.mtime = epoch
                    normalized.uid = 0
                    normalized.gid = 0
                    normalized.uname = ""
                    normalized.gname = ""
                    normalized.mode = 0o755 if current.isdir() else 0o644
                    normalized.pax_headers = {}
                    payload = source.extractfile(current) if current.isfile() else None
                    destination.addfile(normalized, payload)
    target.replace(path)


def _read_project_metadata(root: Path) -> tuple[str, str]:
    try:
        toml_module = importlib.import_module("tomllib")
    except ModuleNotFoundError:  # pragma: no cover - release runner is Python 3.11+
        try:
            toml_module = importlib.import_module("tomli")
        except ModuleNotFoundError as error:
            raise ReleaseArtifactError(
                "Python <3.11 requires tomli to run the release builder"
            ) from error
    project = toml_module.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    name = str(project["name"])
    version = str(project["version"])
    if name != DEFAULT_PACKAGE or STABLE_VERSION_PATTERN.fullmatch(version) is None:
        raise ReleaseArtifactError("project package identity is not a stable SDK release")
    return name, version


def _metadata_projection(message: Any, *, field: str) -> dict[str, str]:
    def exact_header(name: str, *, allow_empty: bool = False) -> str:
        values = message.get_all(name, [])
        if len(values) != 1:
            raise ReleaseArtifactError(f"{field} must contain exactly one {name} header")
        value = str(values[0])
        if not allow_empty and not value:
            raise ReleaseArtifactError(f"{field} contains an empty {name} header")
        return value

    return {
        "name": exact_header("Name"),
        "version": exact_header("Version"),
        "requires_python": exact_header("Requires-Python", allow_empty=True),
    }


def _require_version_module(payload: bytes, *, version: str, field: str) -> None:
    try:
        source = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ReleaseArtifactError(f"{field} version module is not UTF-8") from error
    pattern = re.compile(
        rf'^__version__\s*=\s*["\']{re.escape(version)}["\']\s*$',
        re.MULTILINE,
    )
    if pattern.search(source) is None:
        raise ReleaseArtifactError(f"{field} version module differs from package metadata")


def _wheel_metadata(path: Path) -> dict[str, str]:
    if path.stat().st_size <= 0 or path.stat().st_size > MAX_WHEEL_BYTES:
        raise ReleaseArtifactError("wheel is outside its byte bound")
    try:
        with zipfile.ZipFile(path, "r") as wheel:
            infos = wheel.infolist()
            if not infos or len(infos) > MAX_DISTRIBUTION_ENTRIES:
                raise ReleaseArtifactError("wheel entry count is outside its bound")
            seen: set[str] = set()
            regular_names: set[str] = set()
            captured: dict[str, bytes] = {}
            fingerprints: dict[str, tuple[str, int]] = {}
            expanded_size = 0
            for info in infos:
                name = _safe_archive_path(info.filename, field="wheel")
                if _is_forbidden_credential_path(name):
                    raise ReleaseArtifactError(f"wheel contains a credential-shaped path: {name}")
                if name in seen:
                    raise ReleaseArtifactError(f"wheel contains duplicate path: {name}")
                seen.add(name)
                if info.flag_bits & 0x1:
                    raise ReleaseArtifactError("wheel contains an encrypted entry")
                mode = (info.external_attr >> 16) & 0o170000
                if info.is_dir():
                    if mode not in {0, stat.S_IFDIR}:
                        raise ReleaseArtifactError(f"wheel directory has a special type: {name}")
                    continue
                if mode not in {0, stat.S_IFREG}:
                    raise ReleaseArtifactError(f"wheel entry is not a regular file: {name}")
                expanded_size += info.file_size
                if expanded_size > MAX_EXPANDED_DISTRIBUTION_BYTES:
                    raise ReleaseArtifactError("wheel expanded bytes exceed their bound")
                digest = hashlib.sha256()
                observed = 0
                should_capture = (
                    name.endswith(".dist-info/METADATA")
                    or name.endswith(".dist-info/WHEEL")
                    or name.endswith(".dist-info/RECORD")
                    or name in {"videovector/__init__.py", "videovector/_version.py"}
                )
                if should_capture and info.file_size > MAX_CONTROL_FILE_BYTES:
                    raise ReleaseArtifactError(f"wheel control entry is too large: {name}")
                payload = bytearray() if should_capture else None
                with wheel.open(info, "r") as source:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        observed += len(chunk)
                        if observed > info.file_size:
                            raise ReleaseArtifactError(f"wheel entry exceeds its size: {name}")
                        digest.update(chunk)
                        if payload is not None:
                            payload.extend(chunk)
                if observed != info.file_size:
                    raise ReleaseArtifactError(f"wheel entry size differs: {name}")
                regular_names.add(name)
                fingerprints[name] = (digest.hexdigest(), observed)
                if payload is not None:
                    captured[name] = bytes(payload)
    except zipfile.BadZipFile as error:
        raise ReleaseArtifactError(f"wheel is not a valid ZIP: {error}") from error

    candidates = [name for name in regular_names if name.endswith(".dist-info/METADATA")]
    if len(candidates) != 1:
        raise ReleaseArtifactError("wheel must contain exactly one METADATA file")
    metadata_name = candidates[0]
    dist_info = metadata_name.removesuffix("/METADATA")
    wheel_name = f"{dist_info}/WHEEL"
    record_name = f"{dist_info}/RECORD"
    required_files = {
        metadata_name,
        wheel_name,
        record_name,
        "videovector/__init__.py",
        "videovector/_version.py",
    }
    if not required_files.issubset(regular_names) or any(
        name not in captured for name in required_files
    ):
        raise ReleaseArtifactError("wheel is missing canonical metadata or package entry points")
    if any(
        PurePosixPath(name).parts[0] not in {"videovector", dist_info}
        or name.endswith(".pth")
        or ".data/scripts/" in name
        or name.endswith(".dist-info/entry_points.txt")
        for name in regular_names
    ):
        raise ReleaseArtifactError("wheel contains an unexpected install-time entry point")
    metadata = BytesParser().parsebytes(captured[metadata_name])
    wheel_headers = BytesParser().parsebytes(captured[wheel_name])
    if (
        len(wheel_headers.get_all("Wheel-Version", [])) != 1
        or wheel_headers.get("Root-Is-Purelib") != "true"
    ):
        raise ReleaseArtifactError("wheel metadata is not canonical purelib metadata")

    try:
        record_rows = list(csv.reader(captured[record_name].decode("utf-8").splitlines()))
    except UnicodeDecodeError as error:
        raise ReleaseArtifactError("wheel RECORD is not UTF-8") from error
    record: dict[str, tuple[str, str]] = {}
    for row in record_rows:
        if len(row) != 3:
            raise ReleaseArtifactError("wheel RECORD contains a malformed row")
        name = _safe_archive_path(row[0], field="wheel RECORD")
        if name in record:
            raise ReleaseArtifactError(f"wheel RECORD duplicates path: {name}")
        record[name] = (row[1], row[2])
    if set(record) != regular_names:
        raise ReleaseArtifactError("wheel RECORD inventory differs from the archive")
    for name, (encoded_digest, encoded_size) in record.items():
        if name == record_name:
            if encoded_digest or encoded_size:
                raise ReleaseArtifactError("wheel RECORD must leave its own digest and size empty")
            continue
        if not encoded_digest.startswith("sha256=") or not encoded_size.isdigit():
            raise ReleaseArtifactError(f"wheel RECORD is not SHA-256 bound: {name}")
        raw_digest = encoded_digest.removeprefix("sha256=")
        try:
            decoded_digest = base64.urlsafe_b64decode(
                raw_digest + ("=" * (-len(raw_digest) % 4))
            ).hex()
        except (ValueError, binascii.Error) as error:
            raise ReleaseArtifactError(f"wheel RECORD digest is malformed: {name}") from error
        actual_digest, actual_size = fingerprints[name]
        if decoded_digest != actual_digest or int(encoded_size) != actual_size:
            raise ReleaseArtifactError(f"wheel RECORD differs from bytes: {name}")
    projection = _metadata_projection(metadata, field="wheel METADATA")
    _require_version_module(
        captured["videovector/_version.py"],
        version=projection["version"],
        field="wheel",
    )
    return projection


def _sdist_metadata(path: Path) -> dict[str, str]:
    if path.stat().st_size <= 0 or path.stat().st_size > MAX_SDIST_BYTES:
        raise ReleaseArtifactError("sdist is outside its byte bound")
    regular_names: set[str] = set()
    captured: dict[str, bytes] = {}
    roots: set[str] = set()
    seen: set[str] = set()
    expanded_size = 0
    try:
        with tarfile.open(path, "r:gz") as archive:
            for index, member in enumerate(archive, start=1):
                if index > MAX_DISTRIBUTION_ENTRIES:
                    raise ReleaseArtifactError("sdist entry count exceeds its bound")
                name = _safe_archive_path(member.name, field="sdist")
                if _is_forbidden_credential_path(name):
                    raise ReleaseArtifactError(f"sdist contains a credential-shaped path: {name}")
                if name in seen:
                    raise ReleaseArtifactError(f"sdist contains duplicate path: {name}")
                seen.add(name)
                roots.add(PurePosixPath(name).parts[0])
                if member.isdir():
                    continue
                if not member.isfile():
                    raise ReleaseArtifactError(f"sdist entry is not a regular file: {name}")
                expanded_size += member.size
                if expanded_size > MAX_EXPANDED_DISTRIBUTION_BYTES:
                    raise ReleaseArtifactError("sdist expanded bytes exceed their bound")
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise ReleaseArtifactError(f"cannot read sdist entry: {name}")
                should_capture = (
                    name.endswith("/PKG-INFO")
                    or name.endswith("/pyproject.toml")
                    or name.endswith("/videovector/__init__.py")
                    or name.endswith("/videovector/_version.py")
                )
                if should_capture and member.size > MAX_CONTROL_FILE_BYTES:
                    raise ReleaseArtifactError(f"sdist control entry is too large: {name}")
                observed = 0
                payload = bytearray() if should_capture else None
                while True:
                    chunk = extracted.read(1024 * 1024)
                    if not chunk:
                        break
                    observed += len(chunk)
                    if observed > member.size:
                        raise ReleaseArtifactError(f"sdist entry exceeds its size: {name}")
                    if payload is not None:
                        payload.extend(chunk)
                if observed != member.size:
                    raise ReleaseArtifactError(f"sdist entry size differs: {name}")
                regular_names.add(name)
                if payload is not None:
                    captured[name] = bytes(payload)
    except (tarfile.TarError, EOFError, OSError) as error:
        raise ReleaseArtifactError(f"sdist is not a valid gzip tar: {error}") from error
    if len(roots) != 1:
        raise ReleaseArtifactError("sdist must contain one canonical top-level root")
    root = next(iter(roots))
    metadata_name = f"{root}/PKG-INFO"
    pyproject_name = f"{root}/pyproject.toml"
    version_module_name = f"{root}/videovector/_version.py"
    required_files = {
        metadata_name,
        pyproject_name,
        version_module_name,
        f"{root}/videovector/__init__.py",
    }
    if not required_files.issubset(regular_names) or any(
        name not in captured for name in required_files
    ):
        raise ReleaseArtifactError(
            "sdist must contain canonical project metadata and package entry points"
        )
    metadata = BytesParser().parsebytes(captured[metadata_name])
    try:
        toml_module = importlib.import_module("tomllib")
    except ModuleNotFoundError:  # pragma: no cover - Python 3.9 and 3.10
        toml_module = importlib.import_module("tomli")
    try:
        pyproject = toml_module.loads(captured[pyproject_name].decode("utf-8"))
        project = pyproject["project"]
        build_system = pyproject["build-system"]
    except (UnicodeDecodeError, KeyError, TypeError, ValueError) as error:
        raise ReleaseArtifactError(f"sdist pyproject metadata is invalid: {error}") from error
    metadata_projection = _metadata_projection(metadata, field="sdist PKG-INFO")
    if (
        build_system
        != {
            "requires": ["setuptools==80.10.2", "wheel==0.47.0"],
            "build-backend": "setuptools.build_meta",
        }
        or f"{root}/setup.py" in regular_names
        or project.get("name") != metadata_projection["name"]
        or project.get("version") != metadata_projection["version"]
        or project.get("requires-python", "") != metadata_projection["requires_python"]
        or root != f"{metadata_projection['name']}-{metadata_projection['version']}"
    ):
        raise ReleaseArtifactError("sdist project metadata differs from PKG-INFO")
    _require_version_module(
        captured[version_module_name],
        version=metadata_projection["version"],
        field="sdist",
    )
    return metadata_projection


def _artifact_descriptor(path: Path) -> dict[str, Any]:
    if path.name.endswith(".whl"):
        package_type = "bdist_wheel"
    elif path.name.endswith(".tar.gz"):
        package_type = "sdist"
    else:
        raise ReleaseArtifactError(f"unexpected release artifact: {path.name}")
    return {
        "filename": path.name,
        "path": f"dist/{path.name}",
        "packagetype": package_type,
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
    }


def _uv_version() -> str:
    executable = shutil.which("uv")
    if executable is None:
        return "unavailable"
    try:
        output = _run((executable, "--version"), cwd=Path.cwd(), capture=True)
    except (OSError, ReleaseProcessError, subprocess.CalledProcessError):
        return "unavailable"
    match = re.fullmatch(r"uv (?P<version>[0-9]+\.[0-9]+\.[0-9]+)(?: .*)?", output)
    return match.group("version") if match is not None else "unavailable"


def _tool_versions() -> dict[str, str]:
    versions = {"python": sys.version.split()[0]}
    for distribution in ("build", "setuptools", "twine", "wheel"):
        try:
            versions[distribution] = importlib_metadata.version(distribution)
        except importlib_metadata.PackageNotFoundError:
            versions[distribution] = "unavailable"
    versions["uv"] = _uv_version()
    return versions


def _copy_release_source(
    root: Path,
    destination: Path,
    source_sha: str,
    *,
    allow_dirty: bool,
) -> None:
    if allow_dirty:
        ignored = shutil.ignore_patterns(
            ".git",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            "__pycache__",
            "*.egg-info",
            "build",
            "dist",
            "release-bundle",
        )
        shutil.copytree(root, destination, ignore=ignored)
        return

    archive_path = destination.parent / "source.tar"
    _run(
        ("git", "archive", "--format=tar", f"--output={archive_path}", source_sha),
        cwd=root,
        timeout_seconds=60,
    )
    destination.mkdir()
    with tarfile.open(archive_path, "r:") as archive:
        members = archive.getmembers()
        for member in members:
            relative = PurePosixPath(member.name)
            if (
                relative.is_absolute()
                or not relative.parts
                or any(part in {"", ".", ".."} for part in relative.parts)
                or member.issym()
                or member.islnk()
                or not (member.isdir() or member.isfile())
            ):
                raise ReleaseArtifactError(f"git archive contains an unsafe entry: {member.name}")
        archive.extractall(destination, members=members)
    archive_path.unlink()


def _expected_registry_metadata(
    *,
    package_metadata: Mapping[str, str],
    artifacts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "package": dict(package_metadata),
        "artifacts": sorted(
            (
                {
                    "filename": artifact["filename"],
                    "packagetype": artifact["packagetype"],
                    "sha256": artifact["sha256"],
                    "size": artifact["size"],
                }
                for artifact in artifacts
            ),
            key=lambda artifact: str(artifact["filename"]),
        ),
    }


def _load_json(path: Path, *, field: str) -> Any:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ReleaseArtifactError(f"{field} contains duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        payload = path.read_bytes()
        if not payload or len(payload) > MAX_CONTROL_FILE_BYTES:
            raise ReleaseArtifactError(f"{field} is outside its byte bound")
        return json.loads(payload.decode("utf-8"), object_pairs_hook=unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReleaseArtifactError(f"cannot read {field}: {error}") from error


def _require_exact_keys(value: Mapping[str, Any], keys: set[str], *, field: str) -> None:
    observed = set(value)
    if observed != keys:
        raise ReleaseArtifactError(
            f"{field} keys differ: missing={sorted(keys - observed)}, "
            f"unexpected={sorted(observed - keys)}"
        )


def verify_bundle(
    bundle: Path,
    *,
    source_sha: str | None = None,
    tag_sha: str | None = None,
    source_date_epoch: int | None = None,
    release_body_sha256: str | None = None,
) -> dict[str, Any]:
    manifest_path = bundle / "release-manifest.json"
    manifest_value = _load_json(manifest_path, field="release-manifest.json")
    if not isinstance(manifest_value, dict):
        raise ReleaseArtifactError("release manifest must be a JSON object")
    manifest: dict[str, Any] = manifest_value
    _require_exact_keys(
        manifest,
        {
            "schema_version",
            "package",
            "repository",
            "source_sha",
            "tag",
            "tag_sha",
            "source_date_epoch",
            "release_body_sha256",
            "artifacts",
            "image_digest",
            "registry_metadata_path",
            "registry_metadata_sha256",
            "tool_versions",
        },
        field="release manifest",
    )
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ReleaseArtifactError("unsupported release manifest schema")
    manifest_source_sha = manifest.get("source_sha")
    package = manifest.get("package")
    if (
        not isinstance(manifest_source_sha, str)
        or re.fullmatch(r"[0-9a-f]{40}", manifest_source_sha) is None
        or manifest.get("tag_sha") != manifest_source_sha
        or not isinstance(package, Mapping)
        or set(package) != {"name", "version"}
        or package.get("name") != DEFAULT_PACKAGE
        or not isinstance(package.get("version"), str)
        or STABLE_VERSION_PATTERN.fullmatch(str(package["version"])) is None
        or manifest.get("tag") != f"videovector-v{package['version']}"
        or not isinstance(manifest.get("source_date_epoch"), int)
        or isinstance(manifest["source_date_epoch"], bool)
        or manifest["source_date_epoch"] <= 0
        or not isinstance(manifest.get("release_body_sha256"), str)
        or SHA256_PATTERN.fullmatch(manifest["release_body_sha256"]) is None
        or manifest.get("repository") != DEFAULT_REPOSITORY
        or manifest.get("image_digest") is not None
    ):
        raise ReleaseArtifactError("release provenance fields are invalid")
    tool_versions = manifest.get("tool_versions")
    if not isinstance(tool_versions, Mapping) or dict(tool_versions) != EXPECTED_TOOL_VERSIONS:
        raise ReleaseArtifactError("release tool versions differ from the immutable toolchain")
    if source_sha is not None and manifest.get("source_sha") != source_sha:
        raise ReleaseArtifactError("release bundle source SHA does not match")
    if tag_sha is not None and manifest.get("tag_sha") != tag_sha:
        raise ReleaseArtifactError("release bundle tag SHA does not match")
    if source_date_epoch is not None and manifest.get("source_date_epoch") != source_date_epoch:
        raise ReleaseArtifactError("release bundle commit timestamp does not match")
    if release_body_sha256 is not None:
        expected_body_hash = _require_sha256(
            release_body_sha256,
            "release_body_sha256",
        )
        if manifest.get("release_body_sha256") != expected_body_hash:
            raise ReleaseArtifactError("release body hash does not match")

    bundle_root = bundle.resolve()
    metadata_relative_path = manifest.get("registry_metadata_path")
    if metadata_relative_path != "registry-metadata.json":
        raise ReleaseArtifactError("registry metadata path is not canonical")
    metadata_path = (bundle_root / metadata_relative_path).resolve()
    if metadata_path.parent != bundle_root:
        raise ReleaseArtifactError("registry metadata path escapes the bundle")
    if not metadata_path.is_file():
        raise ReleaseArtifactError("registry metadata file is missing")

    artifact_paths: set[str] = set()
    package_types: set[str] = set()
    descriptors = manifest.get("artifacts")
    if not isinstance(descriptors, list):
        raise ReleaseArtifactError("release artifacts must be a list")
    for descriptor in descriptors:
        if not isinstance(descriptor, Mapping):
            raise ReleaseArtifactError("release artifact descriptor is malformed")
        _require_exact_keys(
            descriptor,
            {"filename", "path", "packagetype", "sha256", "size"},
            field="release artifact descriptor",
        )
        filename = descriptor.get("filename")
        relative_path = descriptor.get("path")
        package_type = descriptor.get("packagetype")
        digest = descriptor.get("sha256")
        size = descriptor.get("size")
        if (
            not isinstance(filename, str)
            or not filename
            or "\\" in filename
            or Path(filename).name != filename
            or not isinstance(relative_path, str)
            or relative_path != f"dist/{filename}"
            or relative_path in artifact_paths
            or package_type not in {"bdist_wheel", "sdist"}
            or package_type in package_types
            or not isinstance(digest, str)
            or SHA256_PATTERN.fullmatch(digest) is None
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
            or size > (MAX_WHEEL_BYTES if package_type == "bdist_wheel" else MAX_SDIST_BYTES)
        ):
            raise ReleaseArtifactError("release artifact path is invalid or duplicated")
        artifact_paths.add(relative_path)
        package_types.add(package_type)
        artifact_path = (bundle_root / relative_path).resolve()
        if artifact_path.parent != (bundle_root / "dist").resolve():
            raise ReleaseArtifactError("release artifact path escapes the bundle")
        if not artifact_path.is_file():
            raise ReleaseArtifactError(f"release artifact is missing: {relative_path}")
        if artifact_path.stat().st_size != size:
            raise ReleaseArtifactError(f"release artifact size mismatch: {relative_path}")
        if sha256_file(artifact_path) != digest:
            raise ReleaseArtifactError(f"release artifact hash mismatch: {relative_path}")
    if len(artifact_paths) != 2 or package_types != {"bdist_wheel", "sdist"}:
        raise ReleaseArtifactError("release bundle must contain exactly one wheel and one sdist")

    wheel_descriptor = next(
        descriptor for descriptor in descriptors if descriptor["packagetype"] == "bdist_wheel"
    )
    sdist_descriptor = next(
        descriptor for descriptor in descriptors if descriptor["packagetype"] == "sdist"
    )
    wheel_metadata = _wheel_metadata(bundle_root / wheel_descriptor["path"])
    if _sdist_metadata(bundle_root / sdist_descriptor["path"]) != wheel_metadata:
        raise ReleaseArtifactError("sdist metadata differs from wheel metadata")
    if package != {
        "name": wheel_metadata["name"],
        "version": wheel_metadata["version"],
    }:
        raise ReleaseArtifactError("release manifest package differs from wheel metadata")

    expected_metadata = _expected_registry_metadata(
        package_metadata=wheel_metadata,
        artifacts=descriptors,
    )
    actual_metadata = _load_json(metadata_path, field="registry-metadata.json")
    if not isinstance(actual_metadata, Mapping):
        raise ReleaseArtifactError("registry metadata must be a JSON object")
    _require_exact_keys(
        actual_metadata,
        {"schema_version", "package", "artifacts"},
        field="registry metadata",
    )
    metadata_package = actual_metadata.get("package")
    if not isinstance(metadata_package, Mapping):
        raise ReleaseArtifactError("registry package metadata is malformed")
    _require_exact_keys(
        metadata_package,
        {"name", "version", "requires_python"},
        field="registry package metadata",
    )
    if actual_metadata != expected_metadata:
        raise ReleaseArtifactError("registry metadata differs from release artifacts")
    expected_metadata_hash = _sha256_bytes(_stable_json_bytes(expected_metadata))
    if expected_metadata_hash != manifest.get("registry_metadata_sha256"):
        raise ReleaseArtifactError("registry metadata hash does not match")
    return manifest


def build_bundle(args: argparse.Namespace) -> None:
    root = Path(args.root).resolve()
    bundle = Path(args.output).resolve()
    release_body_sha256 = _require_sha256(
        args.release_body_sha256,
        "release_body_sha256",
    )
    source_sha = args.source_sha or _git(root, "rev-parse", "HEAD")
    tag_sha = args.tag_sha or _git(root, "rev-list", "-n", "1", args.tag)
    if source_sha != tag_sha:
        raise ReleaseArtifactError("release tag SHA must equal source SHA")
    if not args.allow_dirty and _git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ReleaseArtifactError("release source must be clean")
    source_date_epoch = int(_git(root, "show", "-s", "--format=%ct", source_sha))

    if bundle.exists():
        verify_bundle(
            bundle,
            source_sha=source_sha,
            tag_sha=tag_sha,
            source_date_epoch=source_date_epoch,
            release_body_sha256=release_body_sha256,
        )
        print(f"[release] Reusing verified bundle at {bundle}")
        return

    package_name, package_version = _read_project_metadata(root)
    if args.version is not None and package_version != args.version:
        raise ReleaseArtifactError(
            f"project version {package_version} does not match {args.version}"
        )

    bundle.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{bundle.name}.", dir=str(bundle.parent)))
    try:
        source = staging / "source"
        _copy_release_source(
            root,
            source,
            source_sha,
            allow_dirty=bool(args.allow_dirty),
        )
        dist = staging / "dist"
        dist.mkdir()
        build_environment = {
            "LC_ALL": "C.UTF-8",
            "PYTHONHASHSEED": "0",
            "SOURCE_DATE_EPOCH": str(source_date_epoch),
            "TZ": "UTC",
        }
        _run(
            (
                sys.executable,
                "-m",
                "build",
                "--no-isolation",
                "--outdir",
                str(dist),
            ),
            cwd=source,
            env=build_environment,
            timeout_seconds=90,
        )

        wheels = sorted(dist.glob("*.whl"))
        sdists = sorted(dist.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise ReleaseArtifactError("build must produce exactly one wheel and one sdist")
        normalize_wheel(wheels[0], source_date_epoch)
        normalize_sdist(sdists[0], source_date_epoch)

        wheel_metadata = _wheel_metadata(wheels[0])
        if wheel_metadata["name"] != package_name or wheel_metadata["version"] != package_version:
            raise ReleaseArtifactError("built wheel metadata does not match project metadata")
        artifacts = [_artifact_descriptor(path) for path in sorted((*wheels, *sdists))]
        registry_metadata = _expected_registry_metadata(
            package_metadata=wheel_metadata,
            artifacts=artifacts,
        )
        metadata_path = staging / "registry-metadata.json"
        _write_json(metadata_path, registry_metadata)
        tool_versions = _tool_versions()
        if tool_versions != EXPECTED_TOOL_VERSIONS:
            differences = sorted(
                name
                for name in set(tool_versions) | set(EXPECTED_TOOL_VERSIONS)
                if tool_versions.get(name) != EXPECTED_TOOL_VERSIONS.get(name)
            )
            raise ReleaseArtifactError(
                "release toolchain differs from the immutable policy: " + ", ".join(differences)
            )
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "package": {"name": package_name, "version": package_version},
            "repository": DEFAULT_REPOSITORY,
            "source_sha": source_sha,
            "tag": args.tag,
            "tag_sha": tag_sha,
            "source_date_epoch": source_date_epoch,
            "release_body_sha256": release_body_sha256,
            "artifacts": artifacts,
            "image_digest": None,
            "registry_metadata_path": "registry-metadata.json",
            "registry_metadata_sha256": sha256_file(metadata_path),
            "tool_versions": tool_versions,
        }
        _write_json(staging / "release-manifest.json", manifest)
        shutil.rmtree(source)
        verify_bundle(
            staging,
            source_sha=source_sha,
            tag_sha=tag_sha,
            source_date_epoch=source_date_epoch,
            release_body_sha256=release_body_sha256,
        )
        staging.replace(bundle)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    print(f"[release] Built immutable bundle at {bundle}")


def _registry_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    info = payload.get("info")
    urls = payload.get("urls")
    if not isinstance(info, Mapping) or not isinstance(urls, list):
        raise ReleaseArtifactError("registry returned malformed project metadata")
    artifacts = []
    filenames: set[str] = set()
    for entry in urls:
        if not isinstance(entry, Mapping):
            raise ReleaseArtifactError("registry returned malformed artifact metadata")
        digests = entry.get("digests")
        if not isinstance(digests, Mapping):
            raise ReleaseArtifactError("registry artifact has no digest metadata")
        filename = entry.get("filename")
        package_type = entry.get("packagetype")
        digest = digests.get("sha256")
        size = entry.get("size")
        if (
            not isinstance(filename, str)
            or not filename
            or Path(filename).name != filename
            or filename in filenames
            or package_type not in {"bdist_wheel", "sdist"}
            or not isinstance(digest, str)
            or SHA256_PATTERN.fullmatch(digest) is None
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size <= 0
            or size > (MAX_WHEEL_BYTES if package_type == "bdist_wheel" else MAX_SDIST_BYTES)
        ):
            raise ReleaseArtifactError("registry artifact metadata is invalid or duplicated")
        filenames.add(filename)
        artifacts.append(
            {
                "filename": filename,
                "packagetype": package_type,
                "sha256": digest,
                "size": size,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "package": {
            "name": info.get("name"),
            "version": info.get("version"),
            "requires_python": info.get("requires_python") or "",
        },
        "artifacts": sorted(artifacts, key=lambda artifact: str(artifact["filename"])),
    }


def _registry_artifact_sources(
    payload: Mapping[str, Any],
    *,
    allowed_hosts: frozenset[str],
) -> dict[str, str]:
    urls = payload.get("urls")
    if not isinstance(urls, list):
        raise ReleaseArtifactError("registry returned malformed artifact metadata")
    sources: dict[str, str] = {}
    for entry in urls:
        if not isinstance(entry, Mapping):
            raise ReleaseArtifactError("registry returned malformed artifact metadata")
        filename = entry.get("filename")
        artifact_url = entry.get("url")
        if (
            not isinstance(filename, str)
            or filename in sources
            or not isinstance(artifact_url, str)
            or entry.get("yanked") is not False
        ):
            raise ReleaseArtifactError("registry artifact source is missing, duplicated, or yanked")
        sources[filename] = _require_https_url(
            artifact_url,
            allowed_hosts,
            "registry artifact URL",
        )
    return sources


def _download_registry_artifacts(
    *,
    payload: Mapping[str, Any],
    actual: Mapping[str, Any],
    expected_by_name: Mapping[str, Mapping[str, Any]],
    allowed_hosts: frozenset[str],
    timeout: float,
    destination: Path,
) -> None:
    sources = _registry_artifact_sources(payload, allowed_hosts=allowed_hosts)
    actual_artifacts = actual.get("artifacts")
    if not isinstance(actual_artifacts, list):
        raise ReleaseArtifactError("registry artifact projection is malformed")
    downloaded: dict[str, Path] = {}
    for artifact in actual_artifacts:
        if not isinstance(artifact, Mapping):
            raise ReleaseArtifactError("registry artifact projection is malformed")
        filename = str(artifact["filename"])
        expected = expected_by_name.get(filename)
        if expected is None:
            continue
        expected_size = int(expected["size"])
        package_type = expected.get("packagetype")
        byte_limit = MAX_WHEEL_BYTES if package_type == "bdist_wheel" else MAX_SDIST_BYTES
        if expected_size > byte_limit:
            raise ReleaseArtifactError("distribution exceeds its byte limit")
        artifact_path = destination / filename
        try:
            with _open_registry_url(
                sources[filename],
                timeout=timeout,
                allowed_hosts=allowed_hosts,
            ) as response:
                _stream_registry_artifact(
                    response,
                    destination=artifact_path,
                    expected_size=expected_size,
                    expected_sha256=str(expected["sha256"]),
                    field=f"registry artifact {filename}",
                )
        except urllib.error.HTTPError as error:
            raise ReleaseArtifactError(
                f"cannot download registry artifact {filename}: HTTP {error.code}"
            ) from error
        except (OSError, TimeoutError) as error:
            raise ReleaseArtifactError(
                f"cannot download registry artifact {filename}: {error}"
            ) from error
        downloaded[filename] = artifact_path

    wheel_paths = [
        downloaded[str(artifact["filename"])]
        for artifact in actual_artifacts
        if artifact.get("packagetype") == "bdist_wheel" and str(artifact["filename"]) in downloaded
    ]
    sdist_paths = [
        downloaded[str(artifact["filename"])]
        for artifact in actual_artifacts
        if artifact.get("packagetype") == "sdist" and str(artifact["filename"]) in downloaded
    ]
    package = actual.get("package")
    if not isinstance(package, Mapping):
        raise ReleaseArtifactError("registry package projection is malformed")
    expected_package = {
        "name": package.get("name"),
        "version": package.get("version"),
        "requires_python": package.get("requires_python"),
    }
    for wheel_path in wheel_paths:
        if _wheel_metadata(wheel_path) != expected_package:
            raise ReleaseArtifactError(f"registry wheel metadata differs: {wheel_path.name}")
    for sdist_path in sdist_paths:
        if _sdist_metadata(sdist_path) != expected_package:
            raise ReleaseArtifactError(f"registry sdist metadata differs: {sdist_path.name}")


def _write_missing_artifacts(
    bundle: Path,
    manifest: Mapping[str, Any],
    filenames: Sequence[str],
    output: str | None,
) -> None:
    if output is None:
        return
    destination = Path(output).resolve()
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    descriptors = {
        str(descriptor["filename"]): descriptor for descriptor in manifest.get("artifacts", [])
    }
    for filename in filenames:
        descriptor = descriptors.get(filename)
        if descriptor is None:
            raise ReleaseArtifactError(f"manifest has no artifact named {filename}")
        shutil.copy2(bundle / str(descriptor["path"]), destination / filename)


def registry_status(args: argparse.Namespace) -> int:
    bundle = Path(args.bundle).resolve()
    manifest = verify_bundle(bundle)
    expected = _load_json(
        bundle / manifest["registry_metadata_path"],
        field="registry-metadata.json",
    )
    base_url = (args.base_url or DEFAULT_REGISTRY_URLS[args.registry]).rstrip("/")
    base_host = urllib.parse.urlsplit(base_url).hostname
    if not base_host:
        raise ReleaseArtifactError("registry base URL has no host")
    metadata_hosts = frozenset({base_host.lower()})
    artifact_hosts = (
        TRUSTED_DISTRIBUTION_HOSTS[args.registry] if args.base_url is None else metadata_hosts
    )
    package_name = manifest["package"]["name"]
    version = manifest["package"]["version"]
    url = f"{base_url}/pypi/{package_name}/{version}/json"
    try:
        with _open_registry_url(
            url,
            timeout=args.timeout,
            allowed_hosts=metadata_hosts,
        ) as response:
            payload = json.loads(
                _read_bounded_response(
                    response,
                    max_bytes=MAX_REGISTRY_METADATA_BYTES,
                    field=f"{args.registry} metadata",
                )
            )
    except urllib.error.HTTPError as error:
        if error.code == 404:
            _write_missing_artifacts(
                bundle,
                manifest,
                [str(artifact["filename"]) for artifact in expected["artifacts"]],
                args.write_missing,
            )
            print("missing")
            return 3
        raise ReleaseArtifactError(f"{args.registry} returned HTTP {error.code}") from error
    except (OSError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ReleaseArtifactError(f"cannot query {args.registry}: {error}") from error

    if not isinstance(payload, Mapping):
        raise ReleaseArtifactError("registry returned malformed project metadata")
    actual = _registry_projection(payload)
    if actual["package"] != expected["package"]:
        raise ReleaseArtifactError(f"{args.registry} version exists but package metadata differs")
    expected_by_name = {str(artifact["filename"]): artifact for artifact in expected["artifacts"]}
    actual_by_name = {str(artifact["filename"]): artifact for artifact in actual["artifacts"]}
    unexpected = sorted(set(actual_by_name) - set(expected_by_name))
    if unexpected:
        raise ReleaseArtifactError(
            f"{args.registry} contains unexpected artifacts: {', '.join(unexpected)}"
        )
    conflicts = sorted(
        filename
        for filename, artifact in actual_by_name.items()
        if artifact != expected_by_name[filename]
    )
    if conflicts:
        raise ReleaseArtifactError(
            f"{args.registry} artifact bytes or metadata differ: {', '.join(conflicts)}"
        )
    with tempfile.TemporaryDirectory(prefix="videovector-registry-verify-") as raw_temp:
        _download_registry_artifacts(
            payload=payload,
            actual=actual,
            expected_by_name=expected_by_name,
            allowed_hosts=artifact_hosts,
            timeout=args.timeout,
            destination=Path(raw_temp),
        )
    missing = sorted(set(expected_by_name) - set(actual_by_name))
    if missing:
        _write_missing_artifacts(bundle, manifest, missing, args.write_missing)
        print("partial")
        return 4
    if _sha256_bytes(_stable_json_bytes(actual)) != manifest["registry_metadata_sha256"]:
        raise ReleaseArtifactError(f"{args.registry} metadata hash differs")
    print("exact")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    build = subcommands.add_parser("build", help="build or reuse one release bundle")
    build.add_argument("--root", default=".")
    build.add_argument("--output", required=True)
    build.add_argument("--tag", required=True)
    build.add_argument("--tag-sha")
    build.add_argument("--source-sha")
    build.add_argument("--version")
    build.add_argument("--release-body-sha256", required=True)
    build.add_argument("--allow-dirty", action="store_true")

    verify = subcommands.add_parser("verify-bundle", help="verify bundle hashes")
    verify.add_argument("--bundle", required=True)
    verify.add_argument("--source-sha")
    verify.add_argument("--tag-sha")
    verify.add_argument("--source-date-epoch", type=int)
    verify.add_argument("--release-body-sha256")

    registry = subcommands.add_parser(
        "registry-status",
        help="return exact, missing (exit 3), or fail on conflict",
    )
    registry.add_argument("--bundle", required=True)
    registry.add_argument("--registry", choices=sorted(DEFAULT_REGISTRY_URLS), required=True)
    registry.add_argument("--base-url")
    registry.add_argument("--timeout", type=float, default=30.0)
    registry.add_argument("--write-missing")
    return parser


def _fail(error: BaseException) -> NoReturn:
    print(f"[release] {error}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "build":
            build_bundle(args)
            return 0
        if args.command == "verify-bundle":
            verify_bundle(
                Path(args.bundle).resolve(),
                source_sha=args.source_sha,
                tag_sha=args.tag_sha,
                source_date_epoch=args.source_date_epoch,
                release_body_sha256=args.release_body_sha256,
            )
            print("verified")
            return 0
        if args.command == "registry-status":
            return registry_status(args)
        raise AssertionError(f"unsupported command: {args.command}")
    except ReleaseArtifactError as error:
        _fail(error)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Create, recover, verify, and stage an immutable release bundle.

The helper intentionally uses only the Python standard library.  It never
executes code from an artifact: semantic verification is delegated to the
repository's reviewed release verifier after safe extraction.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

if __package__ in {None, ""}:  # Support direct ``python scripts/...`` execution.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.release_process import ReleaseProcessError, run_release_process

API_ROOT = "https://api.github.com"
API_VERSION = "2026-03-10"
BOT_LOGIN = "vectormethods-public-bot[bot]"
CONTROL_ASSETS = (
    "release-bundle.zip",
    "release-manifest.json",
    "registry-metadata.json",
)
CONTROL_FILE_LIMIT = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = (2 * 1024 * 1024 * 1024) - 1
MAX_ARCHIVE_ENTRIES = 64
MAX_JSON_BYTES = 4 * 1024 * 1024
SETTLEMENT_SECONDS = 30.0
SETTLEMENT_INTERVAL_SECONDS = 0.5
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
INTEGER_PATTERN = re.compile(r"[1-9][0-9]*")
ALLOWED_ASSET_UPLOADERS = frozenset({BOT_LOGIN, "github-actions[bot]"})
ALLOWED_DOWNLOAD_HOST_SUFFIXES = (
    ".github.com",
    ".githubusercontent.com",
)


class ReleaseStagingError(RuntimeError):
    """The durable release bundle or its GitHub state is unsafe."""


def _fail(message: str) -> NoReturn:
    raise ReleaseStagingError(message)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _positive_integer(value: str, field: str) -> int:
    if INTEGER_PATTERN.fullmatch(value) is None:
        _fail(f"{field} must be a positive base-10 integer")
    return int(value)


def _sha256(value: str, field: str) -> str:
    if SHA256_PATTERN.fullmatch(value) is None:
        _fail(f"{field} must be a lowercase SHA-256 digest")
    return value


def _git_sha(value: str, field: str) -> str:
    if GIT_SHA_PATTERN.fullmatch(value) is None:
        _fail(f"{field} must be a full lowercase Git object id")
    return value


def _safe_member_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != name
    ):
        _fail(f"release archive contains an unsafe path: {name!r}")
    return path


def _bundle_files(bundle: Path) -> list[tuple[PurePosixPath, Path]]:
    if not bundle.is_dir() or bundle.is_symlink():
        _fail("release bundle directory is missing or unsafe")
    files: list[tuple[PurePosixPath, Path]] = []
    for candidate in sorted(bundle.rglob("*")):
        relative = PurePosixPath(candidate.relative_to(bundle).as_posix())
        _safe_member_name(relative.as_posix())
        mode = candidate.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            _fail(f"release bundle contains a non-regular file: {relative}")
        files.append((relative, candidate))
    names = {str(relative) for relative, _ in files}
    try:
        manifest = json.loads((bundle / "release-manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReleaseStagingError(f"cannot read release manifest: {error}") from error
    descriptors = manifest.get("artifacts") if isinstance(manifest, Mapping) else None
    if not isinstance(descriptors, list) or not descriptors:
        _fail("release manifest artifact inventory is malformed")
    expected = set(CONTROL_ASSETS[1:])
    for descriptor in descriptors:
        relative_path = descriptor.get("path") if isinstance(descriptor, Mapping) else None
        if not isinstance(relative_path, str):
            _fail("release manifest artifact path is malformed")
        canonical_path = _safe_member_name(relative_path).as_posix()
        if canonical_path in expected:
            _fail("release manifest artifact path is duplicated")
        expected.add(canonical_path)
    if names != expected:
        _fail("release bundle filesystem differs from its closed manifest inventory")
    if not files or len(files) > MAX_ARCHIVE_ENTRIES:
        _fail("release bundle file count is outside its bound")
    total = sum(path.stat().st_size for _, path in files)
    if total <= 0 or total > MAX_ARCHIVE_BYTES:
        _fail("release bundle expanded size is outside its bound")
    return files


def _source_date_epoch(bundle: Path) -> int:
    manifest_path = bundle / "release-manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReleaseStagingError(f"cannot read release manifest: {error}") from error
    epoch = payload.get("source_date_epoch") if isinstance(payload, Mapping) else None
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch <= 0 or epoch > 4_354_819_198:
        _fail("release manifest source_date_epoch is invalid")
    return epoch


def _archive_date_time(bundle: Path) -> tuple[int, int, int, int, int, int]:
    timestamp = time.gmtime(max(_source_date_epoch(bundle), 315532800))
    return (
        timestamp.tm_year,
        timestamp.tm_mon,
        timestamp.tm_mday,
        timestamp.tm_hour,
        timestamp.tm_min,
        timestamp.tm_sec - (timestamp.tm_sec % 2),
    )


def create_deterministic_archive(bundle: Path, archive_path: Path) -> str:
    """Create a byte-stable, uncompressed ZIP from one verified bundle tree."""

    files = _bundle_files(bundle)
    if archive_path.exists() or archive_path.is_symlink():
        _fail("release archive destination must not already exist")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    date_time = _archive_date_time(bundle)
    try:
        with zipfile.ZipFile(
            archive_path,
            "x",
            compression=zipfile.ZIP_STORED,
            allowZip64=True,
        ) as archive:
            for relative, source in files:
                info = zipfile.ZipInfo(relative.as_posix(), date_time=date_time)
                info.compress_type = zipfile.ZIP_STORED
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                info.flag_bits = 0
                with source.open("rb") as input_file, archive.open(info, "w") as output:
                    for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
                        output.write(chunk)
    except BaseException:
        archive_path.unlink(missing_ok=True)
        raise
    size = archive_path.stat().st_size
    if size <= 0 or size > MAX_ARCHIVE_BYTES:
        archive_path.unlink(missing_ok=True)
        _fail("deterministic release archive is outside GitHub's asset byte bound")
    return _sha256_file(archive_path)


def extract_verified_archive(archive_path: Path, destination: Path) -> None:
    """Safely extract a closed, deterministic archive into a new directory."""

    size = archive_path.stat().st_size if archive_path.is_file() else 0
    if size <= 0 or size > MAX_ARCHIVE_BYTES:
        _fail("release archive is outside GitHub's asset byte bound")
    if destination.exists() or destination.is_symlink():
        _fail("release bundle extraction destination must not already exist")
    destination.mkdir(parents=True)
    observed: set[str] = set()
    observed_dates: set[tuple[int, int, int, int, int, int]] = set()
    expanded = 0
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            if archive.comment:
                _fail("release archive comment is not canonical")
            entries = archive.infolist()
            if not entries or len(entries) > MAX_ARCHIVE_ENTRIES:
                _fail("release archive entry count is outside its bound")
            for info in entries:
                relative = _safe_member_name(info.filename)
                if info.filename in observed:
                    _fail(f"release archive contains a duplicate path: {info.filename}")
                observed.add(info.filename)
                observed_dates.add(info.date_time)
                mode = info.external_attr >> 16
                if (
                    info.is_dir()
                    or info.flag_bits & 0x1
                    or info.compress_type != zipfile.ZIP_STORED
                    or info.compress_size != info.file_size
                    or info.extra
                    or info.comment
                    or info.create_system != 3
                    or not stat.S_ISREG(mode)
                    or stat.S_IMODE(mode) != 0o644
                ):
                    _fail(f"release archive entry is not canonical: {info.filename}")
                expanded += info.file_size
                if expanded > MAX_ARCHIVE_BYTES:
                    _fail("release archive expanded size exceeds its bound")
                target = destination.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with archive.open(info, "r") as source, target.open("xb") as output:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > info.file_size:
                            _fail(
                                f"release archive entry exceeds its declared size: {info.filename}"
                            )
                        output.write(chunk)
                if written != info.file_size:
                    _fail(f"release archive entry size differs: {info.filename}")
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    try:
        if not set(CONTROL_ASSETS[1:]).issubset(observed):
            _fail("release archive is missing its control files")
        _bundle_files(destination)
        if observed_dates != {_archive_date_time(destination)}:
            _fail("release archive timestamps are not canonical")
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def _verify_product_bundle(
    *,
    kind: str,
    bundle: Path,
    release_tag: str,
    source_sha: str,
    tag_object_sha: str | None,
    release_body_sha256: str,
) -> None:
    root = Path(__file__).resolve().parents[1]
    try:
        epoch_result = run_release_process(
            ("git", "show", "-s", "--format=%ct", source_sha),
            cwd=root,
            timeout_seconds=30,
        )
        source_date_epoch = epoch_result.stdout.strip()
    except (OSError, ReleaseProcessError) as error:
        raise ReleaseStagingError(
            f"cannot read the authoritative release commit timestamp: {error}"
        ) from error
    if epoch_result.returncode != 0:
        detail = (epoch_result.stderr or epoch_result.stdout).strip()
        _fail(f"cannot read the authoritative release commit timestamp: {detail}")
    if INTEGER_PATTERN.fullmatch(source_date_epoch) is None:
        _fail("authoritative release commit timestamp is invalid")
    command: Sequence[str]
    if kind == "sdk":
        command = (
            sys.executable,
            str(root / "scripts/release_artifacts.py"),
            "verify-bundle",
            "--bundle",
            str(bundle),
            "--source-sha",
            source_sha,
            "--tag-sha",
            source_sha,
            "--source-date-epoch",
            source_date_epoch,
            "--release-body-sha256",
            release_body_sha256,
        )
    elif kind == "mcp":
        if tag_object_sha is None:
            _fail("MCP bundle verification requires expected_tag_object_sha")
        command = (
            "node",
            str(root / "scripts/release-artifacts.mjs"),
            "verify-bundle",
            "--bundle",
            str(bundle),
            "--tag",
            release_tag,
            "--tag-object-sha",
            tag_object_sha,
            "--tag-commit-sha",
            source_sha,
            "--source-sha",
            source_sha,
            "--release-body-sha256",
            release_body_sha256,
        )
    else:
        _fail(f"unsupported release bundle kind: {kind!r}")
    try:
        result = run_release_process(
            command,
            cwd=root,
            timeout_seconds=120,
        )
    except (OSError, ReleaseProcessError) as error:
        raise ReleaseStagingError(f"product bundle verification failed: {error}") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ReleaseStagingError(f"product bundle verification failed: {detail}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: http.client.HTTPMessage,
        new_url: str,
    ) -> None:
        del request, file_pointer, code, message, headers, new_url
        return None


class _AssetRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: http.client.HTTPMessage,
        new_url: str,
    ) -> urllib.request.Request | None:
        del file_pointer, message, headers
        parsed = urllib.parse.urlsplit(new_url)
        hostname = (parsed.hostname or "").lower()
        if (
            code not in {301, 302, 303, 307, 308}
            or parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or not any(
                hostname == suffix.removeprefix(".") or hostname.endswith(suffix)
                for suffix in ALLOWED_DOWNLOAD_HOST_SUFFIXES
            )
        ):
            _fail("GitHub asset download attempted an unsafe redirect")
        headers_without_credentials = {
            key: value
            for key, value in request.header_items()
            if key.lower() not in {"authorization", "cookie", "proxy-authorization"}
        }
        return urllib.request.Request(
            new_url,
            headers=headers_without_credentials,
            method="GET",
        )


@dataclass(frozen=True)
class Asset:
    asset_id: int
    name: str
    state: str
    size: int
    digest: str | None
    uploader: str


class GitHubClient:
    """Small fail-closed GitHub client with bounded responses and uploads."""

    def __init__(self, token: str, repository: str) -> None:
        if not token:
            _fail("GitHub token is required")
        parts = repository.split("/")
        if len(parts) != 2 or any(not part for part in parts):
            _fail("repository must be an owner/name pair")
        self.token = token
        self.repository = repository
        self._opener = urllib.request.build_opener(_NoRedirect())

    def _headers(self, *, accept: str = "application/vnd.github+json") -> dict[str, str]:
        return {
            "Accept": accept,
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "vectormethods-release-stager/1",
            "X-GitHub-Api-Version": API_VERSION,
        }

    def json(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        ok: Sequence[int] = (200,),
    ) -> Any:
        if not path.startswith("/") or "//" in path:
            _fail("GitHub API path is unsafe")
        encoded = None
        headers = self._headers()
        if body is not None:
            encoded = json.dumps(
                body,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{API_ROOT}{path}",
            data=encoded,
            headers=headers,
            method=method,
        )
        try:
            with self._opener.open(request, timeout=30) as response:
                status = int(response.status)
                payload = response.read(MAX_JSON_BYTES + 1)
        except urllib.error.HTTPError as error:
            payload = error.read(MAX_JSON_BYTES + 1)
            if error.code not in ok:
                detail = payload.decode("utf-8", "replace")[:1000]
                raise ReleaseStagingError(
                    f"GitHub API {method} {path} returned {error.code}: {detail}"
                ) from error
            status = error.code
        except (OSError, TimeoutError, urllib.error.URLError) as error:
            raise ReleaseStagingError(f"GitHub API {method} {path} failed: {error}") from error
        if status not in ok:
            _fail(f"GitHub API {method} {path} returned unexpected status {status}")
        if len(payload) > MAX_JSON_BYTES:
            _fail("GitHub API response exceeds its byte bound")
        if not payload:
            return None
        try:
            return json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ReleaseStagingError("GitHub API returned malformed JSON") from error

    def release(self, release_id: int) -> Mapping[str, Any]:
        payload = self.json(
            "GET",
            f"/repos/{self.repository}/releases/{release_id}",
        )
        if not isinstance(payload, Mapping):
            _fail("GitHub Release payload is malformed")
        return payload

    def assets(self, release_id: int) -> list[Asset]:
        payload = self.json(
            "GET",
            f"/repos/{self.repository}/releases/{release_id}/assets?per_page=100",
        )
        if (
            not isinstance(payload, list)
            or len(payload) >= 100
            or any(not isinstance(value, Mapping) for value in payload)
        ):
            _fail("GitHub Release asset inventory is malformed or exceeds its bound")
        result: list[Asset] = []
        names: set[str] = set()
        ids: set[int] = set()
        for value in payload:
            assert isinstance(value, Mapping)
            asset_id = value.get("id")
            name = value.get("name")
            state = value.get("state")
            size = value.get("size")
            digest = value.get("digest")
            uploader = value.get("uploader")
            uploader_login = uploader.get("login") if isinstance(uploader, Mapping) else None
            if (
                isinstance(asset_id, bool)
                or not isinstance(asset_id, int)
                or asset_id <= 0
                or not isinstance(name, str)
                or not name
                or name in names
                or asset_id in ids
                or state not in {"starter", "uploaded"}
                or isinstance(size, bool)
                or not isinstance(size, int)
                or size < 0
                or digest is not None
                and not isinstance(digest, str)
                or not isinstance(uploader_login, str)
            ):
                _fail("GitHub Release asset metadata is malformed or duplicated")
            names.add(name)
            ids.add(asset_id)
            result.append(
                Asset(
                    asset_id=asset_id,
                    name=name,
                    state=state,
                    size=size,
                    digest=digest,
                    uploader=uploader_login,
                )
            )
        return result

    def delete_asset(self, asset_id: int) -> None:
        self.json(
            "DELETE",
            f"/repos/{self.repository}/releases/assets/{asset_id}",
            ok=(204, 404),
        )

    def download_asset(
        self,
        asset_id: int,
        destination: Path,
        *,
        expected_size: int,
        expected_sha256: str,
    ) -> None:
        if destination.exists():
            _fail("asset download destination must not already exist")
        initial_url = f"{API_ROOT}/repos/{self.repository}/releases/assets/{asset_id}"
        request = urllib.request.Request(
            initial_url,
            headers=self._headers(accept="application/octet-stream"),
            method="GET",
        )
        opener = urllib.request.build_opener(_AssetRedirect())
        observed_size = 0
        digest = hashlib.sha256()
        try:
            with opener.open(request, timeout=60) as response, destination.open("xb") as output:
                final_url = urllib.parse.urlsplit(response.geturl())
                hostname = (final_url.hostname or "").lower()
                if final_url.scheme != "https" or not any(
                    hostname == suffix.removeprefix(".") or hostname.endswith(suffix)
                    for suffix in ALLOWED_DOWNLOAD_HOST_SUFFIXES
                ):
                    _fail("GitHub asset download returned an unsafe final URL")
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    observed_size += len(chunk)
                    if observed_size > expected_size:
                        _fail("GitHub release asset exceeds its expected size")
                    digest.update(chunk)
                    output.write(chunk)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        if observed_size != expected_size or digest.hexdigest() != expected_sha256:
            destination.unlink(missing_ok=True)
            _fail("downloaded GitHub release asset bytes differ")

    def upload_asset(
        self,
        release_id: int,
        name: str,
        path: Path,
        content_type: str,
    ) -> None:
        size = path.stat().st_size
        query = urllib.parse.urlencode({"name": name})
        request_path = f"/repos/{self.repository}/releases/{release_id}/assets?{query}"
        connection = http.client.HTTPSConnection("uploads.github.com", timeout=120)
        try:
            connection.putrequest("POST", request_path)
            for key, value in self._headers().items():
                connection.putheader(key, value)
            connection.putheader("Content-Type", content_type)
            connection.putheader("Content-Length", str(size))
            connection.endheaders()
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    connection.send(chunk)
            response = connection.getresponse()
            payload = response.read(MAX_JSON_BYTES + 1)
            status = response.status
        finally:
            connection.close()
        if len(payload) > MAX_JSON_BYTES:
            _fail("GitHub upload response exceeds its byte bound")
        if status not in {201, 422} and status < 500:
            detail = payload.decode("utf-8", "replace")[:1000]
            _fail(f"GitHub release asset upload returned {status}: {detail}")
        if status >= 500:
            raise ReleaseStagingError(
                f"GitHub release asset upload outcome is uncertain after HTTP {status}"
            )


def _require_release_identity(
    client: GitHubClient,
    *,
    release_id: int,
    release_tag: str,
    expected_target_sha: str,
    expected_tag_object_sha: str | None,
    release_body_sha256: str,
    require_draft: bool,
) -> Mapping[str, Any]:
    release = client.release(release_id)
    author = release.get("author")
    if (
        release.get("id") != release_id
        or release.get("tag_name") != release_tag
        or release.get("target_commitish") != expected_target_sha
        or not isinstance(author, Mapping)
        or author.get("login") != BOT_LOGIN
        or not isinstance(release.get("body"), str)
        or hashlib.sha256(str(release["body"]).encode("utf-8")).hexdigest() != release_body_sha256
        or release.get("prerelease") is not False
        or require_draft
        and (release.get("draft") is not True or release.get("immutable") not in {None, False})
    ):
        _fail("GitHub Release identity differs from the exact bot-owned release")

    encoded_tag = urllib.parse.quote(release_tag, safe="")
    ref = client.json(
        "GET",
        f"/repos/{client.repository}/git/ref/tags/{encoded_tag}",
    )
    target = ref.get("object") if isinstance(ref, Mapping) else None
    if not isinstance(target, Mapping):
        _fail("GitHub release tag ref is malformed")
    if expected_tag_object_sha is None:
        if target.get("type") != "commit" or target.get("sha") != expected_target_sha:
            _fail("GitHub lightweight release tag identity differs")
    else:
        if target.get("type") != "tag" or target.get("sha") != expected_tag_object_sha:
            _fail("GitHub annotated release tag object differs")
        tag = client.json(
            "GET",
            f"/repos/{client.repository}/git/tags/{expected_tag_object_sha}",
        )
        peeled = tag.get("object") if isinstance(tag, Mapping) else None
        if (
            not isinstance(peeled, Mapping)
            or tag.get("tag") != release_tag
            or peeled.get("type") != "commit"
            or peeled.get("sha") != expected_target_sha
        ):
            _fail("GitHub annotated release tag does not peel to the expected commit")
    return release


def _asset_map(client: GitHubClient, release_id: int) -> dict[str, Asset]:
    assets = client.assets(release_id)
    unexpected = sorted(asset.name for asset in assets if asset.name not in CONTROL_ASSETS)
    if unexpected:
        _fail(f"GitHub draft contains unexpected assets: {', '.join(unexpected)}")
    return {asset.name: asset for asset in assets}


def _require_exact_asset(asset: Asset, *, size: int, digest: str) -> None:
    if (
        asset.state != "uploaded"
        or asset.size != size
        or asset.digest != f"sha256:{digest}"
        or asset.uploader not in ALLOWED_ASSET_UPLOADERS
    ):
        _fail(f"GitHub release asset {asset.name!r} differs from the expected bytes")


def _settle_asset(
    client: GitHubClient,
    *,
    release_id: int,
    name: str,
    path: Path,
    content_type: str,
    identity_check: Callable[[], None],
) -> None:
    expected_size = path.stat().st_size
    expected_digest = _sha256_file(path)
    deadline = time.monotonic() + SETTLEMENT_SECONDS
    uploaded = False
    last_error: BaseException | None = None
    while time.monotonic() < deadline:
        current = _asset_map(client, release_id).get(name)
        if current is not None and current.state == "uploaded":
            if (
                current.size == expected_size
                and current.uploader in ALLOWED_ASSET_UPLOADERS
                and current.digest in {None, ""}
            ):
                time.sleep(SETTLEMENT_INTERVAL_SECONDS)
                continue
            _require_exact_asset(
                current,
                size=expected_size,
                digest=expected_digest,
            )
            return
        if current is not None:
            if (
                current.state != "starter"
                or current.size != 0
                or current.uploader not in ALLOWED_ASSET_UPLOADERS
            ):
                _fail(f"refusing to replace noncanonical GitHub asset {name!r}")
            identity_check()
            try:
                client.delete_asset(current.asset_id)
            except ReleaseStagingError as error:
                last_error = error
            time.sleep(SETTLEMENT_INTERVAL_SECONDS)
            continue
        if not uploaded:
            uploaded = True
            identity_check()
            try:
                client.upload_asset(release_id, name, path, content_type)
            except (OSError, TimeoutError, ReleaseStagingError) as error:
                last_error = error
        time.sleep(SETTLEMENT_INTERVAL_SECONDS)
    _fail(f"GitHub release asset {name!r} did not settle: {last_error}")


def reconcile_draft_assets(
    client: GitHubClient,
    *,
    release_id: int,
    archive_path: Path,
    bundle: Path,
    identity_check: Callable[[], None],
) -> None:
    expected = (
        ("release-bundle.zip", archive_path, "application/zip"),
        (
            "release-manifest.json",
            bundle / "release-manifest.json",
            "application/json",
        ),
        (
            "registry-metadata.json",
            bundle / "registry-metadata.json",
            "application/json",
        ),
    )
    for name, path, _ in expected:
        size = path.stat().st_size if path.is_file() else 0
        limit = MAX_ARCHIVE_BYTES if name == "release-bundle.zip" else CONTROL_FILE_LIMIT
        if size <= 0 or size > limit:
            _fail(f"release asset {name!r} is outside its byte bound")
    for name, path, content_type in expected:
        _settle_asset(
            client,
            release_id=release_id,
            name=name,
            path=path,
            content_type=content_type,
            identity_check=identity_check,
        )
    identity_check()
    final = _asset_map(client, release_id)
    if set(final) != set(CONTROL_ASSETS):
        _fail("GitHub draft release asset inventory is incomplete")
    for name, path, _ in expected:
        _require_exact_asset(
            final[name],
            size=path.stat().st_size,
            digest=_sha256_file(path),
        )


def _complete_transport_directory(archive_path: Path, bundle: Path) -> None:
    if archive_path.name != "release-bundle.zip":
        _fail("release archive filename must be release-bundle.zip")
    transport = archive_path.parent
    for name in CONTROL_ASSETS[1:]:
        source = bundle / name
        destination = transport / name
        if destination.exists() or destination.is_symlink():
            _fail("release transport control destination already exists")
        with source.open("rb") as input_file, destination.open("xb") as output:
            for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
                output.write(chunk)
        if _sha256_file(destination) != _sha256_file(source):
            _fail(f"release transport control file {name!r} differs")
    entries = list(transport.iterdir())
    if {candidate.name for candidate in entries} != set(CONTROL_ASSETS) or any(
        not candidate.is_file() or candidate.is_symlink() for candidate in entries
    ):
        _fail("release transport directory inventory is not canonical")


def _recover_source_bundle(
    client: GitHubClient,
    *,
    release_id: int,
    asset_id: int,
    expected_sha256: str,
    archive_path: Path,
    bundle: Path,
) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    assets = client.assets(release_id)
    matches = [asset for asset in assets if asset.asset_id == asset_id]
    if len(matches) != 1:
        _fail("bundle source asset id is absent or ambiguous")
    source = matches[0]
    if source.name != "release-bundle.zip":
        _fail("bundle source asset is not release-bundle.zip")
    _require_exact_asset(source, size=source.size, digest=expected_sha256)
    if source.size <= 0 or source.size > MAX_ARCHIVE_BYTES:
        _fail("bundle source asset is outside its byte bound")
    client.download_asset(
        source.asset_id,
        archive_path,
        expected_size=source.size,
        expected_sha256=expected_sha256,
    )
    extract_verified_archive(archive_path, bundle)


def _write_output(name: str, value: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as destination:
            destination.write(f"{name}={value}\n")


def assemble(args: argparse.Namespace) -> None:
    source_sha = _git_sha(args.expected_target_sha, "expected_target_sha")
    body_sha = _sha256(args.release_body_sha256, "release_body_sha256")
    tag_object_sha = (
        _git_sha(args.expected_tag_object_sha, "expected_tag_object_sha")
        if args.expected_tag_object_sha
        else None
    )
    source_values = (
        args.bundle_source_release_id,
        args.bundle_source_asset_id,
        args.bundle_source_sha256,
    )
    if any(source_values) and not all(source_values):
        _fail("bundle source release id, asset id, and SHA-256 must be supplied together")
    bundle = Path(args.bundle).resolve()
    archive_path = Path(args.archive).resolve()
    if all(source_values):
        token = os.environ.get(args.github_token_env, "")
        client = GitHubClient(token, args.repository)
        source_release_id = _positive_integer(
            args.bundle_source_release_id,
            "bundle_source_release_id",
        )
        source_asset_id = _positive_integer(
            args.bundle_source_asset_id,
            "bundle_source_asset_id",
        )
        source_digest = _sha256(
            args.bundle_source_sha256,
            "bundle_source_sha256",
        )
        _require_release_identity(
            client,
            release_id=source_release_id,
            release_tag=args.release_tag,
            expected_target_sha=source_sha,
            expected_tag_object_sha=tag_object_sha,
            release_body_sha256=body_sha,
            require_draft=False,
        )
        _recover_source_bundle(
            client,
            release_id=source_release_id,
            asset_id=source_asset_id,
            expected_sha256=source_digest,
            archive_path=archive_path,
            bundle=bundle,
        )
    else:
        _verify_product_bundle(
            kind=args.kind,
            bundle=bundle,
            release_tag=args.release_tag,
            source_sha=source_sha,
            tag_object_sha=tag_object_sha,
            release_body_sha256=body_sha,
        )
        create_deterministic_archive(bundle, archive_path)

    with tempfile.TemporaryDirectory(prefix="release-bundle-semantic-") as raw_temp:
        extracted = Path(raw_temp) / "bundle"
        extract_verified_archive(archive_path, extracted)
        _verify_product_bundle(
            kind=args.kind,
            bundle=extracted,
            release_tag=args.release_tag,
            source_sha=source_sha,
            tag_object_sha=tag_object_sha,
            release_body_sha256=body_sha,
        )
    _complete_transport_directory(archive_path, bundle)
    _write_output("bundle_sha256", _sha256_file(archive_path))
    print(f"assembled sha256:{_sha256_file(archive_path)}")


def stage(args: argparse.Namespace) -> None:
    source_sha = _git_sha(args.expected_target_sha, "expected_target_sha")
    body_sha = _sha256(args.release_body_sha256, "release_body_sha256")
    tag_object_sha = (
        _git_sha(args.expected_tag_object_sha, "expected_tag_object_sha")
        if args.expected_tag_object_sha
        else None
    )
    draft_release_id = _positive_integer(args.draft_release_id, "draft_release_id")
    token = os.environ.get(args.github_token_env, "")
    client = GitHubClient(token, args.repository)
    bundle = Path(args.bundle).resolve()
    archive_path = Path(args.archive).resolve()

    materialize(args)

    def require_identity() -> None:
        _require_release_identity(
            client,
            release_id=draft_release_id,
            release_tag=args.release_tag,
            expected_target_sha=source_sha,
            expected_tag_object_sha=tag_object_sha,
            release_body_sha256=body_sha,
            require_draft=True,
        )

    require_identity()
    reconcile_draft_assets(
        client,
        release_id=draft_release_id,
        archive_path=archive_path,
        bundle=bundle,
        identity_check=require_identity,
    )
    require_identity()
    _write_output("bundle_sha256", _sha256_file(archive_path))
    _write_output("draft_release_id", str(draft_release_id))
    print(f"staged sha256:{_sha256_file(archive_path)}")


def materialize(args: argparse.Namespace) -> None:
    source_sha = _git_sha(args.expected_target_sha, "expected_target_sha")
    body_sha = _sha256(args.release_body_sha256, "release_body_sha256")
    tag_object_sha = (
        _git_sha(args.expected_tag_object_sha, "expected_tag_object_sha")
        if args.expected_tag_object_sha
        else None
    )
    bundle = Path(args.bundle).resolve()
    archive_path = Path(args.archive).resolve()
    transport_entries = list(archive_path.parent.iterdir())
    if {candidate.name for candidate in transport_entries} != set(CONTROL_ASSETS) or any(
        not candidate.is_file() or candidate.is_symlink() for candidate in transport_entries
    ):
        _fail("downloaded release transport inventory is not canonical")
    for name in CONTROL_ASSETS[1:]:
        size = (archive_path.parent / name).stat().st_size
        if size <= 0 or size > CONTROL_FILE_LIMIT:
            _fail(f"release transport control file {name!r} exceeds its byte bound")
    extract_verified_archive(archive_path, bundle)
    for name in CONTROL_ASSETS[1:]:
        if _sha256_file(archive_path.parent / name) != _sha256_file(bundle / name):
            _fail(f"release transport control file {name!r} differs from the archive")
    _verify_product_bundle(
        kind=args.kind,
        bundle=bundle,
        release_tag=args.release_tag,
        source_sha=source_sha,
        tag_object_sha=tag_object_sha,
        release_body_sha256=body_sha,
    )
    print(f"materialized sha256:{_sha256_file(archive_path)}")


def _identity_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--kind", choices=("sdk", "mcp"), required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--expected-target-sha", required=True)
    parser.add_argument("--expected-tag-object-sha", default="")
    parser.add_argument("--release-body-sha256", required=True)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--archive", required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    assemble_parser = commands.add_parser("assemble")
    _identity_arguments(assemble_parser)
    assemble_parser.add_argument("--repository", required=True)
    assemble_parser.add_argument("--bundle-source-release-id", default="")
    assemble_parser.add_argument("--bundle-source-asset-id", default="")
    assemble_parser.add_argument("--bundle-source-sha256", default="")
    assemble_parser.add_argument("--github-token-env", default="GITHUB_TOKEN")
    stage_parser = commands.add_parser("stage")
    _identity_arguments(stage_parser)
    stage_parser.add_argument("--repository", required=True)
    stage_parser.add_argument("--draft-release-id", required=True)
    stage_parser.add_argument("--github-token-env", default="GITHUB_TOKEN")
    materialize_parser = commands.add_parser("materialize")
    _identity_arguments(materialize_parser)
    return parser


def main() -> int:
    try:
        args = _parser().parse_args()
        if args.command == "assemble":
            assemble(args)
        elif args.command == "stage":
            stage(args)
        else:
            materialize(args)
    except ReleaseStagingError as error:
        print(f"[release-staging] {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

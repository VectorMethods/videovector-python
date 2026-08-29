from __future__ import annotations

import hashlib
import http.client
import importlib.util
import json
import re
import sys
import zipfile
from argparse import Namespace
from pathlib import Path
from types import ModuleType

import pytest


def _module() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "release_draft_staging.py"
    spec = importlib.util.spec_from_file_location("release_draft_staging", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


release = _module()


def _bundle(root: Path) -> Path:
    bundle = root / "bundle"
    (bundle / "dist").mkdir(parents=True)
    (bundle / "release-manifest.json").write_text(
        json.dumps(
            {
                "artifacts": [{"path": "dist/artifact.bin"}],
                "source_date_epoch": 1_700_000_001,
            }
        ),
        encoding="utf-8",
    )
    (bundle / "registry-metadata.json").write_text("{}\n", encoding="utf-8")
    (bundle / "dist" / "artifact.bin").write_bytes(b"artifact bytes")
    return bundle


def test_archive_is_deterministic_closed_and_round_trips(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    first_digest = release.create_deterministic_archive(bundle, first)
    second_digest = release.create_deterministic_archive(bundle, second)

    assert first.read_bytes() == second.read_bytes()
    assert first_digest == hashlib.sha256(first.read_bytes()).hexdigest()
    assert second_digest == first_digest
    extracted = tmp_path / "extracted"
    release.extract_verified_archive(first, extracted)
    assert (extracted / "dist" / "artifact.bin").read_bytes() == b"artifact bytes"
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == sorted(archive.namelist())
        assert all(info.compress_type == zipfile.ZIP_STORED for info in archive.infolist())
        assert all(not info.extra and not info.comment for info in archive.infolist())


def test_archive_rejects_non_regular_bundle_member(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    (bundle / "unsafe-link").symlink_to(bundle / "registry-metadata.json")

    with pytest.raises(release.ReleaseStagingError, match="non-regular"):
        release.create_deterministic_archive(bundle, tmp_path / "bundle.zip")


def test_archive_rejects_file_outside_closed_manifest_inventory(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    (bundle / "untracked-secret").write_text("must not ship", encoding="utf-8")

    with pytest.raises(release.ReleaseStagingError, match="closed manifest"):
        release.create_deterministic_archive(bundle, tmp_path / "bundle.zip")


def test_extraction_rejects_traversal_and_removes_partial_tree(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
        info = zipfile.ZipInfo("../escape")
        info.create_system = 3
        info.external_attr = 0o100644 << 16
        archive.writestr(info, b"unsafe")
    destination = tmp_path / "output"

    with pytest.raises(release.ReleaseStagingError, match="unsafe path"):
        release.extract_verified_archive(archive_path, destination)

    assert not destination.exists()
    assert not (tmp_path / "escape").exists()


def test_asset_redirect_strips_token_and_rejects_untrusted_host() -> None:
    request = release.urllib.request.Request(
        "https://api.github.com/repos/VectorMethods/repo/releases/assets/7",
        headers={"Authorization": "Bearer secret", "Accept": "application/octet-stream"},
    )
    handler = release._AssetRedirect()
    redirected = handler.redirect_request(
        request,
        None,
        302,
        "Found",
        http.client.HTTPMessage(),
        "https://release-assets.githubusercontent.com/object",
    )

    assert redirected is not None
    assert redirected.get_header("Authorization") is None
    with pytest.raises(release.ReleaseStagingError, match="unsafe redirect"):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            http.client.HTTPMessage(),
            "https://attacker.invalid/object",
        )


def test_assemble_rejects_partial_resume_identity_before_network(tmp_path: Path) -> None:
    args = Namespace(
        kind="sdk",
        repository="VectorMethods/videovector-python",
        release_tag="videovector-v1.2.3",
        expected_target_sha="a" * 40,
        expected_tag_object_sha="",
        release_body_sha256="b" * 64,
        bundle_source_release_id="41",
        bundle_source_asset_id="",
        bundle_source_sha256="c" * 64,
        bundle=str(tmp_path / "bundle"),
        archive=str(tmp_path / "release-bundle.zip"),
        github_token_env="GITHUB_TOKEN",
    )

    with pytest.raises(release.ReleaseStagingError, match="supplied together"):
        release.assemble(args)


class _IdentityClient:
    repository = "VectorMethods/videovector-python"

    def __init__(self, *, author: str = release.BOT_LOGIN) -> None:
        self.author = author

    def release(self, release_id: int) -> dict[str, object]:
        return {
            "id": release_id,
            "tag_name": "videovector-v1.2.3",
            "target_commitish": "a" * 40,
            "author": {"login": self.author},
            "body": "release body",
            "prerelease": False,
            "draft": True,
            "immutable": False,
        }

    def json(self, method: str, path: str) -> dict[str, object]:
        assert method == "GET"
        assert path.endswith("videovector-v1.2.3")
        return {"object": {"type": "commit", "sha": "a" * 40}}


def test_release_identity_requires_exact_bot_owned_draft() -> None:
    body_hash = hashlib.sha256(b"release body").hexdigest()
    release._require_release_identity(
        _IdentityClient(),
        release_id=42,
        release_tag="videovector-v1.2.3",
        expected_target_sha="a" * 40,
        expected_tag_object_sha=None,
        release_body_sha256=body_hash,
        require_draft=True,
    )

    with pytest.raises(release.ReleaseStagingError, match="bot-owned"):
        release._require_release_identity(
            _IdentityClient(author="octocat"),
            release_id=42,
            release_tag="videovector-v1.2.3",
            expected_target_sha="a" * 40,
            expected_tag_object_sha=None,
            release_body_sha256=body_hash,
            require_draft=True,
        )


class _UncertainUploadClient:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.upload_calls = 0
        self.visible = False

    def assets(self, release_id: int) -> list[object]:
        assert release_id == 42
        if not self.visible:
            return []
        return [
            release.Asset(
                asset_id=7,
                name="release-bundle.zip",
                state="uploaded",
                size=self.path.stat().st_size,
                digest=f"sha256:{release._sha256_file(self.path)}",
                uploader="github-actions[bot]",
            )
        ]

    def upload_asset(
        self,
        release_id: int,
        name: str,
        path: Path,
        content_type: str,
    ) -> None:
        assert (release_id, name, path, content_type) == (
            42,
            "release-bundle.zip",
            self.path,
            "application/zip",
        )
        self.upload_calls += 1
        self.visible = True
        raise release.ReleaseStagingError("lost upload response")


def test_uncertain_upload_settles_by_exact_digest_readback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "release-bundle.zip"
    path.write_bytes(b"durable bundle")
    client = _UncertainUploadClient(path)
    monkeypatch.setattr(release, "SETTLEMENT_INTERVAL_SECONDS", 0)

    release._settle_asset(
        client,
        release_id=42,
        name="release-bundle.zip",
        path=path,
        content_type="application/zip",
        identity_check=lambda: None,
    )

    assert client.upload_calls == 1


class _ReplaceStarterClient:
    def __init__(self, path: Path, events: list[str]) -> None:
        self.path = path
        self.events = events
        self.state = "starter"

    def assets(self, _release_id: int) -> list[release.Asset]:
        if self.state == "starter":
            return [
                release.Asset(
                    asset_id=7,
                    name="release-bundle.zip",
                    state="starter",
                    size=0,
                    digest=None,
                    uploader="github-actions[bot]",
                )
            ]
        if self.state == "absent":
            return []
        return [
            release.Asset(
                asset_id=8,
                name="release-bundle.zip",
                state="uploaded",
                size=self.path.stat().st_size,
                digest=f"sha256:{release._sha256_file(self.path)}",
                uploader="github-actions[bot]",
            )
        ]

    def delete_asset(self, asset_id: int) -> None:
        assert asset_id == 7
        self.events.append("delete")
        self.state = "absent"

    def upload_asset(
        self,
        _release_id: int,
        _name: str,
        _path: Path,
        _content_type: str,
    ) -> None:
        self.events.append("upload")
        self.state = "uploaded"


def test_draft_identity_is_revalidated_immediately_before_each_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "release-bundle.zip"
    path.write_bytes(b"durable bundle")
    events: list[str] = []
    client = _ReplaceStarterClient(path, events)
    monkeypatch.setattr(release, "SETTLEMENT_INTERVAL_SECONDS", 0)

    release._settle_asset(
        client,
        release_id=42,
        name="release-bundle.zip",
        path=path,
        content_type="application/zip",
        identity_check=lambda: events.append("identity"),
    )

    assert events == ["identity", "delete", "identity", "upload"]


def test_materialize_rejects_wrapper_drift_and_verifies_inner_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _bundle(tmp_path)
    transport = tmp_path / "transport"
    archive = transport / "release-bundle.zip"
    release.create_deterministic_archive(source, archive)
    release._complete_transport_directory(archive, source)
    verifier = monkeypatch.setattr(release, "_verify_product_bundle", lambda **_kwargs: None)
    del verifier
    args = Namespace(
        kind="sdk",
        release_tag="videovector-v1.2.3",
        expected_target_sha="a" * 40,
        expected_tag_object_sha="",
        release_body_sha256="b" * 64,
        bundle=str(tmp_path / "materialized"),
        archive=str(archive),
    )

    release.materialize(args)
    assert (tmp_path / "materialized" / "dist" / "artifact.bin").is_file()

    (transport / "registry-metadata.json").write_text('{"drift":true}', encoding="utf-8")
    args.bundle = str(tmp_path / "drifted")
    with pytest.raises(release.ReleaseStagingError, match="differs from the archive"):
        release.materialize(args)


def test_release_workflow_gates_publishers_on_exact_draft_staging() -> None:
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    for name in (
        "draft_release_id",
        "bundle_source_release_id",
        "bundle_source_asset_id",
        "bundle_source_sha256",
    ):
        assert f"      {name}:" in workflow
    assert "DRAFT_RELEASE_ID: ${{ inputs.draft_release_id }}" in workflow
    assert '--bundle-source-release-id "$BUNDLE_SOURCE_RELEASE_ID"' in workflow
    assert '--bundle-source-asset-id "$BUNDLE_SOURCE_ASSET_ID"' in workflow
    assert '--bundle-source-sha256 "$BUNDLE_SOURCE_SHA256"' in workflow
    assert workflow.count("if: ${{ needs.guard.outputs.resume != 'true' }}") == 1
    assert "path: release-transport/" in workflow
    assert workflow.count("release_draft_staging.py materialize") == 3
    assert workflow.index("Assemble fresh or recovered bytes without write credentials") < (
        workflow.index("Reverify and reconcile the exact draft assets")
    )
    assert workflow.index("Reverify and reconcile the exact draft assets") < workflow.index(
        "Upload immutable verified release bundle"
    )
    assert "scripts/release_draft_staging.py stage" in workflow
    assert (
        "contents: write"
        not in workflow[workflow.index("  build:") : workflow.index("  stage-draft:")]
    )
    build = workflow[workflow.index("  build:") : workflow.index("  stage-draft:")]
    assert "id-token: write" not in build
    assert "attestations: write" not in build
    assert build.index("Run full source checks for fresh and resumed operations") < build.index(
        "Assemble fresh or recovered bytes without write credentials"
    )
    assert build.index("Assemble fresh or recovered bytes without write credentials") < build.index(
        "Install and smoke exact wheel and sdist bytes"
    )
    assert "password:" not in workflow
    assert "TWINE_PASSWORD" not in workflow
    assert workflow.count("with OIDC trusted publishing") == 2
    assert workflow.count('python-version: "3.11.13"') == 7
    job_timeouts = [
        int(value)
        for value in re.findall(r"^    timeout-minutes: ([0-9]+)$", workflow, re.MULTILINE)
    ]
    assert job_timeouts == [5, 25, 7, 7, 6, 7, 6]
    assert sum(job_timeouts) == 63

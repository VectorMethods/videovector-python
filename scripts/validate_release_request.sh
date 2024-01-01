#!/usr/bin/env bash
set -euo pipefail

required_environment=(
  DRAFT_RELEASE_ID
  EXPECTED_TARGET_SHA
  GITHUB_ACTOR
  GITHUB_OUTPUT
  GITHUB_REF
  GITHUB_REPOSITORY
  GITHUB_SHA
  OPERATION_NONCE
  RELEASE_BODY_SHA256
  RELEASE_TAG
  RELEASE_TAG_PREFIX
)
for name in "${required_environment[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "${name} is required." >&2
    exit 1
  fi
done

if [[ "$GITHUB_ACTOR" != "vectormethods-public-bot[bot]" &&
  "$GITHUB_ACTOR" != "vectormethods-public-bot" ]]; then
  echo "Release workflow may only be dispatched by vectormethods-public-bot." >&2
  exit 1
fi
if [[ ! "$EXPECTED_TARGET_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "expected_target_sha must be a full lowercase 40-character Git commit SHA." >&2
  exit 1
fi
if [[ ! "$RELEASE_BODY_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
  echo "release_body_sha256 must be a lowercase SHA-256 digest." >&2
  exit 1
fi
if [[ ! "$OPERATION_NONCE" =~ ^[0-9a-f]{64}$ ]]; then
  echo "operation_nonce must be a lowercase SHA-256 digest." >&2
  exit 1
fi
if [[ "$GITHUB_REPOSITORY" != "VectorMethods/videovector-python" ]]; then
  echo "Release workflow repository identity is invalid." >&2
  exit 1
fi
if [[ ! "$DRAFT_RELEASE_ID" =~ ^[1-9][0-9]*$ ]]; then
  echo "draft_release_id must be a positive base-10 integer." >&2
  exit 1
fi
bundle_source_count=0
for value in \
  "${BUNDLE_SOURCE_RELEASE_ID:-}" \
  "${BUNDLE_SOURCE_ASSET_ID:-}" \
  "${BUNDLE_SOURCE_SHA256:-}"; do
  if [[ -n "$value" ]]; then
    bundle_source_count=$((bundle_source_count + 1))
  fi
done
if [[ "$bundle_source_count" != 0 && "$bundle_source_count" != 3 ]]; then
  echo "bundle source release id, asset id, and SHA-256 must be supplied together." >&2
  exit 1
fi
if [[ "$bundle_source_count" == 3 ]]; then
  if [[ ! "$BUNDLE_SOURCE_RELEASE_ID" =~ ^[1-9][0-9]*$ ||
    ! "$BUNDLE_SOURCE_ASSET_ID" =~ ^[1-9][0-9]*$ ||
    ! "$BUNDLE_SOURCE_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
    echo "bundle source identity is malformed." >&2
    exit 1
  fi
  resume=true
else
  resume=false
fi
if [[ "$RELEASE_TAG" != "$RELEASE_TAG_PREFIX"* ]]; then
  echo "Release tag does not have the required repository prefix." >&2
  exit 1
fi
version="${RELEASE_TAG#"$RELEASE_TAG_PREFIX"}"
if ! VERSION="$version" python - <<'PY'
import os
import re
import sys

version = os.environ["VERSION"]
canonical_semver = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
)
sys.exit(0 if canonical_semver.fullmatch(version) else 1)
PY
then
  echo "Release tag does not contain a valid release version." >&2
  exit 1
fi

tag_ref="refs/tags/${RELEASE_TAG}"
if [[ "$GITHUB_REF" != "$tag_ref" ]]; then
  echo "Release workflow must be dispatched on the exact release tag ref." >&2
  exit 1
fi
if ! git show-ref --verify --quiet "$tag_ref"; then
  echo "Release tag ref is unavailable in the checked-out repository." >&2
  exit 1
fi
if [[ "$(git cat-file -t "$tag_ref")" != "commit" ]]; then
  echo "SDK releases require a lightweight tag that directly names the release commit." >&2
  exit 1
fi

source_sha="$(git rev-parse --verify "${tag_ref}^{commit}")"
checkout_sha="$(git rev-parse --verify "HEAD^{commit}")"
if [[ "$source_sha" != "$EXPECTED_TARGET_SHA" ||
  "$checkout_sha" != "$EXPECTED_TARGET_SHA" ||
  "$GITHUB_SHA" != "$EXPECTED_TARGET_SHA" ]]; then
  echo "Release tag, checkout, event SHA, and expected target SHA must match exactly." >&2
  exit 1
fi
expected_operation_nonce="$(
  REPOSITORY="${GITHUB_REPOSITORY#*/}" \
    TAG="$RELEASE_TAG" \
    TARGET_SHA="$source_sha" \
    BODY_SHA256="$RELEASE_BODY_SHA256" \
    python - <<'PY'
import hashlib
import json
import os

payload = {
    "body_sha256": os.environ["BODY_SHA256"],
    "repo": os.environ["REPOSITORY"],
    "tag": os.environ["TAG"],
    "tag_commit_sha": os.environ["TARGET_SHA"],
    "tag_object_sha": os.environ["TARGET_SHA"],
}
canonical = (
    json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
).encode("utf-8")
print(hashlib.sha256(canonical).hexdigest())
PY
)"
if [[ "$OPERATION_NONCE" != "$expected_operation_nonce" ]]; then
  echo "operation_nonce does not bind the exact repository, tag, commit, and release body." >&2
  exit 1
fi

{
  echo "resume=$resume"
  echo "source_sha=$source_sha"
  echo "version=$version"
} >>"$GITHUB_OUTPUT"

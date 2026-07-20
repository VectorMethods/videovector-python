#!/usr/bin/env bash
set -euo pipefail

required_environment=(
  EXPECTED_TARGET_SHA
  GITHUB_ACTOR
  GITHUB_OUTPUT
  GITHUB_REF
  GITHUB_SHA
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
if [[ "$RELEASE_TAG" != "$RELEASE_TAG_PREFIX"* ]]; then
  echo "Release tag does not have the required repository prefix." >&2
  exit 1
fi
version="${RELEASE_TAG#"$RELEASE_TAG_PREFIX"}"
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([a-z0-9.-]+)?$ ]]; then
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

source_sha="$(git rev-parse --verify "${tag_ref}^{commit}")"
checkout_sha="$(git rev-parse --verify "HEAD^{commit}")"
if [[ "$source_sha" != "$EXPECTED_TARGET_SHA" ||
  "$checkout_sha" != "$EXPECTED_TARGET_SHA" ||
  "$GITHUB_SHA" != "$EXPECTED_TARGET_SHA" ]]; then
  echo "Release tag, checkout, event SHA, and expected target SHA must match exactly." >&2
  exit 1
fi

{
  echo "source_sha=$source_sha"
  echo "version=$version"
} >>"$GITHUB_OUTPUT"

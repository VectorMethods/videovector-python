#!/usr/bin/env bash

set -euo pipefail

UV_VERSION="0.11.29"
UV_LINUX_X86_64_SHA256="04f8b82f5d47f0512dcd32c67a4a6f16a0ea27c81537c338fd0ad6b23cebe829"
RUNNER_TEMP="${RUNNER_TEMP:?RUNNER_TEMP is required}"
GITHUB_PATH="${GITHUB_PATH:?GITHUB_PATH is required}"

archive="$(mktemp "${RUNNER_TEMP}/uv.XXXXXX.tar.gz")"
install_dir="$(mktemp -d "${RUNNER_TEMP}/reviewed-uv.XXXXXX")"
cleanup() {
  rm -f "$archive"
}
trap cleanup EXIT

curl \
  --proto '=https' \
  --tlsv1.2 \
  --retry 3 \
  --retry-all-errors \
  --fail \
  --silent \
  --show-error \
  --location \
  --output "$archive" \
  "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz"
printf '%s  %s\n' "$UV_LINUX_X86_64_SHA256" "$archive" | sha256sum --check -
tar \
  --extract \
  --gzip \
  --no-same-owner \
  --file "$archive" \
  --directory "$install_dir" \
  --strip-components=1 \
  "uv-x86_64-unknown-linux-gnu/uv"
test -f "$install_dir/uv"
test ! -L "$install_dir/uv"
chmod 0755 "$install_dir/uv"
observed_version="$("$install_dir/uv" --version)"
if [[ "$observed_version" != "uv ${UV_VERSION} "* ]]; then
  echo "Unexpected uv version: ${observed_version}" >&2
  exit 1
fi
printf '%s\n' "$install_dir" >>"$GITHUB_PATH"

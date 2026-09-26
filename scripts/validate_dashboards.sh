#!/usr/bin/env bash
set -euo pipefail

# Validates every dashboards/*.json: must be valid JSON, and its top-level
# "uid" must equal its filename stem (the convention documented in
# README.md). uid == filename also guarantees uid uniqueness, since two
# files cannot share one name in the same directory.

cd "$(dirname "$0")/.."

shopt -s nullglob
files=(dashboards/*.json)

if [ ${#files[@]} -eq 0 ]; then
  echo "no dashboard JSON files found under dashboards/" >&2
  exit 1
fi

exit_status=0
for f in "${files[@]}"; do
  if ! err=$(jq empty "$f" 2>&1); then
    echo "INVALID JSON: $f: $err" >&2
    exit_status=1
    continue
  fi
  stem=$(basename "$f" .json)
  uid=$(jq -r '.uid // ""' "$f")
  if [ "$uid" != "$stem" ]; then
    echo "UID MISMATCH: $f has uid='$uid', expected '$stem'" >&2
    exit_status=1
  fi
done

exit "$exit_status"

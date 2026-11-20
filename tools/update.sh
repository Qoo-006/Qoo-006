#!/bin/bash
# Rebuild the profile cards and push them if anything changed.
# PROFILE_GH_USER: gh account to push as (uses its token, so the active gh account is never switched).
set -euo pipefail
cd "$(dirname "$0")/.."

git pull --ff-only -q
python3 tools/build_profile.py
git add assets
if git diff --cached --quiet; then
  echo "no change"
  exit 0
fi
git commit -q -m "Update profile cards ($(date +%Y-%m-%d))"

if [ -n "${PROFILE_GH_USER:-}" ]; then
  GH_TOKEN="$(gh auth token --user "$PROFILE_GH_USER")" git \
    -c credential.helper= \
    -c 'credential.helper=!f() { echo username=x-access-token; echo "password=$GH_TOKEN"; }; f' \
    push -q origin main
else
  git push -q origin main
fi
echo "pushed $(git rev-parse --short HEAD)"

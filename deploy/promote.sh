#!/usr/bin/env bash
# Promote whatever is running on staging to prod (same image, no rebuild), and follow the run.
#
#   deploy/promote.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

echo "Promoting the image running on staging to prod..."
gh workflow run promote.yml --repo "$REPO_SLUG"
sleep 5
run_id=$(gh run list --repo "$REPO_SLUG" --workflow promote.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch "$run_id" --repo "$REPO_SLUG" --exit-status

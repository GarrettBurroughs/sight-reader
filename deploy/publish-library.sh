#!/usr/bin/env bash
# Publish the locally built library (pipeline/data/library) as a new version and point
# library.version at it. Commit library.version afterwards; the next image build includes it.
#
#   deploy/publish-library.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

LIB=pipeline/data/library
[ -f "$LIB/library.sqlite" ] || { echo "No library at $LIB; run pipeline/catalog.py first." >&2; exit 1; }

# Named by content, so publishing the same library twice is a no-op.
VERSION="lib-$(date +%Y%m%d)-$(sha256sum "$LIB/library.sqlite" | cut -c1-10)"
TARBALL="build/$VERSION.tar.gz"
DEST="gs://$LIBRARY_BUCKET/$VERSION.tar.gz"

if gcloud storage objects describe "$DEST" >/dev/null 2>&1; then
  echo "$VERSION is already published."
else
  mkdir -p build
  tar -czf "$TARBALL" -C "$LIB" library.sqlite excerpts exercises
  gcloud storage cp "$TARBALL" "$DEST"
  rm "$TARBALL"
fi
echo "$VERSION" > library.version
echo "library.version -> $VERSION (commit it to deploy)"

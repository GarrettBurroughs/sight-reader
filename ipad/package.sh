#!/usr/bin/env bash
# Zip SightReader.swiftpm so it can be opened in Swift Playgrounds on the iPad.
# Usage: ipad/package.sh [output-dir]   (default: ipad/build)
# Tip: ipad/package.sh /mnt/c/Users/garre/OneDrive/SightReader  then open it from the Files app.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
out="${1:-$here/build}"
mkdir -p "$out"

python3 -I - "$here" "$out/SightReader.swiftpm.zip" <<'EOF'
import pathlib, sys, zipfile

root, dest = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
pkg = root / "SightReader.swiftpm"
with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(pkg.rglob("*")):
        if f.is_file() and ":" not in f.name and f.name != ".DS_Store":
            z.write(f, f.relative_to(root))
print(dest)
EOF

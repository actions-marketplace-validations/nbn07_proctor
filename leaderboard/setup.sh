#!/usr/bin/env bash
# Clone every suite repository at its pinned commit into leaderboard/work/.
#   bash leaderboard/setup.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HERE/work"
python3 - "$HERE" <<'PY'
import json, os, subprocess, sys
here = sys.argv[1]
suite = json.load(open(os.path.join(here, "suite.json")))
for r in suite["repos"]:
    dest = os.path.join(here, "work", r["name"])
    if not os.path.isdir(dest):
        subprocess.run(["git", "clone", "--quiet", r["url"], dest], check=True)
    subprocess.run(["git", "-C", dest, "fetch", "--quiet", "origin"], check=False)
    subprocess.run(["git", "-C", dest, "checkout", "--quiet", r["commit"]], check=True)
    if r.get("setup"):
        subprocess.run(r["setup"], shell=True, cwd=dest, check=True)
    print(f"  ✓ {r['name']} @ {r['commit'][:10]}  ({r['tasks']} tasks)")
PY

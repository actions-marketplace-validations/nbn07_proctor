#!/usr/bin/env bash
# Run agents over the whole suite and build the leaderboard.
#
#   bash leaderboard/run.sh gold noop claude-code codex aider     # agents from agents.json
#   RUN_ID=2026-11-01 TIMEOUT=1800 bash leaderboard/run.sh claude-code
#   LIMIT=5 bash leaderboard/run.sh claude-code     # pilot: the first 5 tasks, spread across the repositories
#   PREAMBLE=preamble-pressure.md bash leaderboard/run.sh claude-code   # pressure condition
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%d-%H%M%S)}"
TIMEOUT="${TIMEOUT:-1800}"
OUT="$HERE/results/$RUN_ID"
mkdir -p "$OUT"
[ "$#" -gt 0 ] || { echo "usage: run.sh AGENT [AGENT...]  (names from agents.json)"; exit 2; }

python3 - "$HERE" "$OUT" "$@" <<'PY'
import json, os, platform, subprocess, sys, time
here, out, agents = sys.argv[1], sys.argv[2], sys.argv[3:]
conf = json.load(open(os.path.join(here, "agents.json")))
missing = [a for a in agents if a not in conf]
if missing:
    sys.exit(f"unknown agent(s): {missing}; edit leaderboard/agents.json")
versions = {}
for a in agents:
    p = subprocess.run(conf[a]["version"], shell=True, capture_output=True, text=True)
    versions[a] = (p.stdout or p.stderr).strip().splitlines()[0] if (p.stdout or p.stderr).strip() else "unknown"
proctor_v = subprocess.run(["proctor", "--version"], capture_output=True, text=True).stdout.strip()
json.dump({"run_id": os.path.basename(out), "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "proctor": proctor_v, "agents": {a: {"cmd": conf[a]["cmd"], "version": versions[a]} for a in agents},
           "platform": platform.platform(), "python": platform.python_version()},
          open(os.path.join(out, "meta.json"), "w"), indent=2)
for a in agents:
    print(f"  {a}: {versions[a]}")
PY

python3 - "$HERE" "$OUT" "$TIMEOUT" "${LIMIT:-0}" "${PREAMBLE:-preamble.md}" "$@" <<'PY'
import json, os, shutil, subprocess, sys
here, out, timeout, limit, preamble, agents = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5], sys.argv[6:]
shutil.copy(os.path.join(here, preamble), os.path.join(out, "preamble-used.md"))  # record the exact prompt
conf = json.load(open(os.path.join(here, "agents.json")))
suite = json.load(open(os.path.join(here, "suite.json")))
task_files = {r["name"]: os.path.join(here, r["task_file"]) for r in suite["repos"]}
if limit > 0:
    # a pilot: take tasks round-robin across repositories so every repo is represented
    docs = {n: json.load(open(f)) for n, f in task_files.items()}
    picked, i = {n: [] for n in docs}, 0
    while sum(map(len, picked.values())) < limit and i < max(len(d["tasks"]) for d in docs.values()):
        for n, d in docs.items():
            if i < len(d["tasks"]) and sum(map(len, picked.values())) < limit:
                picked[n].append(d["tasks"][i])
        i += 1
    os.makedirs(os.path.join(out, "_tasks"), exist_ok=True)
    for n, d in docs.items():
        task_files[n] = os.path.join(out, "_tasks", n + ".json") if picked[n] else None
        if picked[n]:
            json.dump(dict(d, tasks=picked[n]), open(task_files[n], "w"), indent=2)
    print(f"pilot: {limit} tasks ({', '.join(f'{n} {len(t)}' for n, t in picked.items() if t)})")
for r in suite["repos"]:
    if not task_files[r["name"]]:
        continue
    repo_out = os.path.join(out, r["name"])
    args = ["proctor", "bench", "run", task_files[r["name"]], "--repo", os.path.join(here, "work", r["name"]),
            "--cmd", r.get("test_command") or suite["test_command"], "--preamble", os.path.join(here, preamble),
            "--out", repo_out, "--timeout", timeout]
    for a in agents:
        args += ["--agent", f"{a}={conf[a]['cmd']}" if conf[a]["cmd"] not in ("gold", "noop") else conf[a]["cmd"]]
    print(f"\n== {r['name']} ({r['tasks']} tasks)", flush=True)
    subprocess.run(args, check=False)
PY

python3 "$HERE/aggregate.py" "$OUT"
echo "leaderboard: $OUT/LEADERBOARD.md"

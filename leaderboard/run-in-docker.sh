#!/usr/bin/env bash
# Run the ProctorBench leaderboard on your own machine (made for a Mac with Docker Desktop; works on Linux too).
# Every agent runs inside a throwaway container, never directly on your computer.
#
#   bash leaderboard/run-in-docker.sh check                 # is Docker ready? builds the image
#   bash leaderboard/run-in-docker.sh login-claude          # one time: connect your Claude subscription
#   bash leaderboard/run-in-docker.sh login-codex           # optional, one time: connect ChatGPT for Codex
#   bash leaderboard/run-in-docker.sh sanity                # built-in gold + noop agents (free, ~15 min)
#   bash leaderboard/run-in-docker.sh pilot claude-code     # 5 tasks: real time per task
#   bash leaderboard/run-in-docker.sh full claude-code      # all 38 tasks (add codex etc. to compare)
#   bash leaderboard/run-in-docker.sh pressure claude-code  # all 38 tasks, prompt says only passing tests count
#   bash leaderboard/run-in-docker.sh impossible claude-code codex   # tasks whose visible tests contradict the fix
#   bash leaderboard/run-in-docker.sh extend                  # neutral (x3 Claude, x1 Codex) + pressure runs on the newer repositories
#   bash leaderboard/run-in-docker.sh results               # where the latest LEADERBOARD.md is
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
IMAGE=proctorbench
HOMEVOL=proctorbench-home          # keeps agent logins between runs
ENVF="$HERE/.env"                  # your tokens; never committed (see .gitignore)

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
die()  { printf '\n\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

need_docker() {
  command -v docker >/dev/null 2>&1 || die "Docker isn't installed. Install Docker Desktop from https://www.docker.com/products/docker-desktop/ and open it once."
  docker info >/dev/null 2>&1 || die "Docker Desktop isn't running. Open it (whale icon in the menu bar), wait until it says 'running', then try again."
}

build() {
  need_docker
  say "Building the benchmark image (first time: about 3–5 minutes)…"
  docker build -t "$IMAGE" "$HERE"
}

# docker run with the repo mounted at /proctor, the login volume at /home/bench and your tokens
dock() {
  local tty=(-i); [ -t 0 ] && tty=(-it)
  local envs=(); [ -f "$ENVF" ] && envs=(--env-file "$ENVF")
  # (the ${x[@]+...} form keeps macOS's bash 3.2 happy with empty arrays)
  docker run --rm "${tty[@]}" ${envs[@]+"${envs[@]}"} -e TIMEOUT -e LIMIT -e RUN_ID -e PREAMBLE -e REPOS \
    -v "$ROOT":/proctor -v "$HOMEVOL":/home/bench -w /proctor "$IMAGE" "$@"
}

# keep the Mac awake until this script exits
awake() { command -v caffeinate >/dev/null 2>&1 && { caffeinate -dimsu -w $$ & } ; true; }

set_env() {  # set_env KEY VALUE  -> writes/replaces KEY in leaderboard/.env
  touch "$ENVF"; chmod 600 "$ENVF"
  grep -v "^$1=" "$ENVF" > "$ENVF.tmp" || true
  printf '%s=%s\n' "$1" "$2" >> "$ENVF.tmp"; mv "$ENVF.tmp" "$ENVF"; chmod 600 "$ENVF"
}

bench() {  # bench RUN_ID AGENT... (LIMIT may be set)
  local id="$1"; shift
  docker image inspect "$IMAGE" >/dev/null 2>&1 || build
  if printf '%s\n' "$@" | grep -qx claude-code; then
    grep -q '^CLAUDE_CODE_OAUTH_TOKEN=.' "$ENVF" 2>/dev/null || grep -q '^ANTHROPIC_API_KEY=.' "$ENVF" 2>/dev/null \
      || die "Claude Code isn't connected yet. Run: bash leaderboard/run-in-docker.sh login-claude"
  fi
  say "Running: $* (run id $id). You can leave this running; keep the Mac plugged in with the lid open."
  export RUN_ID="$id" LIMIT="${LIMIT:-0}"
  awake
  dock bash -c '
    set -e
    pip install --user --quiet /proctor
    bash leaderboard/setup.sh
    bash leaderboard/run.sh "$@"' _ "$@"
  summary "$id"
}

summary() {  # summary RUN_ID: time per task, from the results (runs in the container: no Python needed on the Mac)
  dock python3 - "leaderboard/results/$1" <<'PY'
import glob, json, os, sys
run = sys.argv[1]
by = {}
for p in glob.glob(os.path.join(run, "*", "*.json")):
    d = json.load(open(p))
    if d.get("kind") == "bench-results":
        by.setdefault(d["agent"], []).extend(d["attempts"])
print()
for agent, at in sorted(by.items()):
    for a in at:
        print(f"    {agent:12s} {a['task'][:28]:28s} {a['outcome']:9s} {(a.get('agent_seconds') or 0):6.0f}s  exit={a.get('agent_exit')}")
for agent, at in sorted(by.items()):
    secs = [a.get("agent_seconds") or 0 for a in at]
    avg = sum(secs) / max(len(secs), 1)
    res = sum(a["outcome"] == "resolved" for a in at); fl = sum(a["outcome"] == "flagged" for a in at)
    err = sum(a["outcome"] == "error" for a in at)
    print(f"  {agent:12s} {len(at):2d} tasks · {res} resolved · {fl} flagged · {err} errors · "
          f"avg {avg/60:.1f} min/task → about {avg*38/3600:.1f} h for all 38 tasks")
print(f"\n  Leaderboard: proctor/{run}/LEADERBOARD.md")
PY
}

cmd="${1:-help}"; shift || true
case "$cmd" in
  check)
    build
    say "✓ Docker is ready and the image is built."
    dock bash -c 'echo "  claude: $(claude --version 2>/dev/null)"; echo "  codex:  $(codex --version 2>/dev/null)"; echo "  python: $(python3 --version)"'
    ;;
  login-claude)
    docker image inspect "$IMAGE" >/dev/null 2>&1 || build
    say "Connecting Claude Code to your Claude subscription."
    echo "A link will appear. Open it in your browser, sign in, approve, and paste the code back here."
    echo "At the end Claude Code prints a long token starting with sk-ant-oat… Copy it."
    dock claude setup-token || true
    printf '\nPaste the token here (it stays hidden) and press Enter: '
    read -rs tok; echo
    [ -n "$tok" ] || die "No token pasted. Run login-claude again."
    set_env CLAUDE_CODE_OAUTH_TOKEN "$tok"
    say "Checking the connection…"
    dock claude -p "Reply with just the word: ready" && say "✓ Claude Code is connected." \
      || die "Claude Code couldn't use that token. Run login-claude again and paste the whole token."
    ;;
  login-codex)
    docker image inspect "$IMAGE" >/dev/null 2>&1 || build
    say "Connecting Codex to your ChatGPT account."
    echo "Codex will show a short code and a link. Open the link, sign in, and enter the code."
    dock codex login --device-auth
    dock codex login status && say "✓ Codex is connected."
    ;;
  sanity)
    bench "sanity-$(date +%Y%m%d-%H%M)" gold noop
    echo "  Expect: gold 38 resolved, noop 0 resolved. Anything else means the setup is broken; send me the output."
    ;;
  pilot)
    [ "$#" -gt 0 ] || die "Say which agent, e.g.: bash leaderboard/run-in-docker.sh pilot claude-code"
    LIMIT="${LIMIT:-5}"; bench "pilot-$(date +%Y%m%d-%H%M)" "$@"
    ;;
  full)
    [ "$#" -gt 0 ] || die "Say which agent(s), e.g.: bash leaderboard/run-in-docker.sh full claude-code"
    LIMIT=0; bench "full-$(date +%Y%m%d-%H%M)" "$@"
    ;;
  pressure)
    [ "$#" -gt 0 ] || die "Say which agent(s), e.g.: bash leaderboard/run-in-docker.sh pressure claude-code"
    export PREAMBLE=preamble-pressure.md
    LIMIT=0; bench "pressure-$(date +%Y%m%d-%H%M)" "$@"
    ;;
  impossible)
    [ "$#" -gt 0 ] || die "Say which agent(s), e.g.: bash leaderboard/run-in-docker.sh impossible claude-code codex"
    docker image inspect "$IMAGE" >/dev/null 2>&1 || build
    id="impossible-$(date +%Y%m%d-%H%M)"
    say "Running impossible tasks: $* (run id $id). Keep the Mac plugged in with the lid open."
    awake
    dock bash -c '
      set -e
      pip install --user --quiet /proctor
      bash leaderboard/setup.sh
      out="leaderboard/results/$0"
      for a in "$@"; do python3 leaderboard/impossible.py run --agent "$a" --out "$out" ${REPOS:+--repos $REPOS}; done
      python3 leaderboard/impossible.py summary "$out"' "$id" "$@"
    ;;
  extend)
    # Every condition on the repositories added later, so all repositories are covered the same way.
    export REPOS="${REPOS:-cachetools pyparsing}"
    for i in 1 2 3; do LIMIT=0; unset PREAMBLE; bench "full-ext$i-$(date +%Y%m%d-%H%M)" claude-code; done
    LIMIT=0; unset PREAMBLE; bench "full-ext-codex-$(date +%Y%m%d-%H%M)" codex
    export PREAMBLE=preamble-pressure.md
    LIMIT=0; bench "pressure-ext-$(date +%Y%m%d-%H%M)" claude-code codex
    ;;
  results)
    latest="$(ls -td "$HERE"/results/*/ 2>/dev/null | head -1)"
    [ -n "$latest" ] || die "No runs yet."
    latest="${latest%/}"; summary "${latest##*/}"
    ;;
  *)
    sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
    ;;
esac

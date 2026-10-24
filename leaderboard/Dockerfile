# A disposable environment for leaderboard runs. Agents that skip permission prompts must run in here,
# never on your workstation.
#
#   docker build -t proctorbench leaderboard/
#   docker run --rm -it -e ANTHROPIC_API_KEY -e OPENAI_API_KEY -e GEMINI_API_KEY \
#       -v "$PWD":/proctor -w /proctor proctorbench bash
#   # inside: pip install -e . && bash leaderboard/setup.sh && bash leaderboard/run.sh gold noop claude-code codex
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates nodejs npm \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pytest aider-chat \
    && npm install -g @anthropic-ai/claude-code @openai/codex @google/gemini-cli
RUN git config --global user.email bench@example.com && git config --global user.name bench

# A disposable environment for leaderboard runs. Agents that skip permission prompts must run in here,
# never on your workstation. The easy way to use it is leaderboard/run-in-docker.sh, which builds this
# image and runs everything for you. By hand:
#
#   docker build -t proctorbench leaderboard/
#   docker run --rm -it -e CLAUDE_CODE_OAUTH_TOKEN -e OPENAI_API_KEY -e GEMINI_API_KEY \
#       -v "$PWD":/proctor -w /proctor proctorbench bash
#   # inside: pip install --user /proctor && bash leaderboard/setup.sh && bash leaderboard/run.sh gold noop claude-code
FROM python:3.12-slim
# Node 22 from NodeSource: Gemini CLI needs Node 20+, newer than some Debian releases ship
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pytest aider-chat \
    && npm install -g @anthropic-ai/claude-code @openai/codex @google/gemini-cli
RUN git config --system user.email bench@example.com && git config --system user.name bench \
    && git config --system --add safe.directory '*'
# Agents run as an ordinary user: Claude Code refuses to skip permission prompts as root.
RUN useradd --create-home --uid 1000 bench
USER bench
ENV PATH=/home/bench/.local/bin:$PATH PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /proctor

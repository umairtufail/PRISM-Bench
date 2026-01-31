FROM ghcr.io/astral-sh/uv:python3.13-bookworm

RUN adduser agent
USER agent
WORKDIR /home/agent

# Copy project files
COPY pyproject.toml uv.lock README.md ./
COPY baseline_agent baseline_agent

# Install dependencies
RUN \
    --mount=type=cache,target=/home/agent/.cache/uv,uid=1000 \
    uv sync --locked

# The entrypoint accepts --host, --port, --card-url as required by AgentBeats
ENTRYPOINT ["uv", "run", "python", "baseline_agent/agent.py"]
CMD ["--host", "0.0.0.0"]
EXPOSE 9019


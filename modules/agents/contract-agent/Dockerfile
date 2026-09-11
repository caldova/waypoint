FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.8.23 /uv /uvx /bin/

# Install dependencies from the frozen lock file first so this layer caches
# independently of source changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy the rest of the agent (main.py, instructions, agent.yaml, .agent_configs).
COPY . .

EXPOSE 8088

# castia serves all registered protocols; app.run() defaults to 0.0.0.0:8088.
CMD ["uv", "run", "--frozen", "--no-sync", "python", "main.py"]

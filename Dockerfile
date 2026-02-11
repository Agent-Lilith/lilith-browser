FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev 2>/dev/null || uv sync --no-dev

COPY . .
RUN uv sync --frozen --no-dev 2>/dev/null || uv sync --no-dev

ENV PYTHONPATH=/app
EXPOSE 8001

CMD ["uv", "run", "python", "main.py", "mcp", "--transport", "streamable-http", "--port", "8001"]

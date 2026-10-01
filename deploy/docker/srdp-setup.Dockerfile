FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src/ src/
RUN uv sync --frozen --no-dev --extra ducklake

ENV PATH="/app/.venv/bin:${PATH}"

USER nobody

ENTRYPOINT ["python", "-m", "srdp.setup"]

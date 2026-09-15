FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
WORKDIR /app

# deps layer (cached until pyproject/lock change) — --no-dev drops basedpyright
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# app code, then install the project itself (package mode → uv_build)
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "router.main:app", "--host", "0.0.0.0", "--port", "8000"]
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.25 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    DATA_DIR=/app/data

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY tcg_pulse ./tcg_pulse
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/data && chown app /app/data

USER app
VOLUME /app/data
# One sync of every game, then exit: non-zero when a game is still missing after its retries.
CMD ["python", "-m", "tcg_pulse", "sync"]

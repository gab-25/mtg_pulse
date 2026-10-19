FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.25 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN DEBUG=1 SECRET_KEY=build DATABASE_URL=postgres://build@localhost/build python manage.py collectstatic --noinput \
    && useradd --create-home --uid 1000 app \
    && chmod +x docker-entrypoint.sh

USER app
EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["gunicorn", "mtg_pulse.wsgi", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60"]

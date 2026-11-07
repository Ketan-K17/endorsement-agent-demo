# Render free web service (ADR-0024, ADR-0027). Build: docker build -t endorsement-agent .
# Run: docker run --env-file .env -p 7860:7860 endorsement-agent
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
# The app reads skills/ and fixtures/documents/ beside src/, so the project stays in /app.
COPY src ./src
COPY skills ./skills
COPY fixtures/documents ./fixtures/documents
RUN uv sync --frozen --no-dev

RUN useradd --create-home app
USER app

# Render sets PORT. Trusting every proxy only sets the scheme (https, for the Secure cookie);
# the visitor IP comes from CLIENT_IP_HEADER, never X-Forwarded-For (ADR-0027).
CMD ["sh", "-c", "exec uvicorn endorsement_agent.api:create_app --factory --host 0.0.0.0 --port ${PORT:-7860} --proxy-headers --forwarded-allow-ips '*'"]

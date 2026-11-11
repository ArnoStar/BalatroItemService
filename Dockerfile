# syntax=docker/dockerfile:1
# The item service in a container: http://<host>:8000 (docs at /docs).
# Items and trades are kept in the PostgreSQL database of BALATRO_ITEMS_DATABASE_URL.
#
#   docker build --network host -t balatro-items .
#   docker run -p 8004:8000 -e BALATRO_ITEMS_DATABASE_URL=postgresql://... balatro-items
#
# (--network host: the build downloads through this machine's connection, which
# also works behind a VPN whose MTU is smaller than Docker's bridge.)

FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim
RUN useradd --system --uid 10001 --no-create-home items
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    BALATRO_ITEMS_HOST=0.0.0.0 \
    BALATRO_ITEMS_PORT=8000
USER items
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
CMD ["balatro-items"]

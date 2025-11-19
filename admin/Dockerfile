FROM python:3.11-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_PREFERENCE=only-system \
    PATH="/usr/src/app/.venv/bin:$PATH"

WORKDIR /usr/src/app

COPY pyproject.toml uv.lock* ./
COPY admin/ ./admin/
COPY shared/ ./shared/

# Install uv
RUN pip install --no-cache-dir uv

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project \
    && adduser -D appuser \
    && chown -R appuser:appuser .

USER appuser

CMD ["gunicorn", "-c", "admin/gunicorn_conf.py"]

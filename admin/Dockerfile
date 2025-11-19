FROM ghcr.io/astral-sh/uv:0.5-python3.13-alpine

WORKDIR /usr/src/app

COPY . .

RUN uv sync --frozen --no-install-project --group admin --no-group bot --no-group dev \
    && adduser -D appuser \
    && chown -R appuser:appuser .

USER appuser

CMD ["gunicorn", "-c", "admin/gunicorn_conf.py"]

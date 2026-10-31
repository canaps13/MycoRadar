FROM python:3.12-slim-trixie@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159 AS api-runtime
COPY --from=ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 /uv /bin/uv
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/api/src \
    PATH=/app/.venv/bin:$PATH
COPY pyproject.toml uv.lock ./
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then \
      SSL_CERT_FILE=/run/secrets/build_ca uv sync --locked --no-dev; \
    else uv sync --locked --no-dev; fi
COPY alembic.ini ./
COPY api ./api
RUN useradd --uid 10001 --create-home appuser
USER appuser
EXPOSE 8000
CMD ["uvicorn", "mycoradar.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Explicit offline raster target; heavy libraries stay outside the default HTTP image.
FROM api-runtime AS raster-job
USER root
RUN apt-get update \
    && apt-get install --no-install-recommends -y libexpat1 \
    && rm -rf /var/lib/apt/lists/*
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then \
      SSL_CERT_FILE=/run/secrets/build_ca uv sync --locked --no-dev --group geo; \
    else uv sync --locked --no-dev --group geo; fi
USER appuser
CMD ["python", "-m", "mycoradar.raster_job", "--help"]

FROM api-runtime AS api

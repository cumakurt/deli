# deli - Ultra high-performance load testing framework
# Multi-stage build for minimal image size

# ---- builder ----
FROM python:3.12-alpine AS builder

WORKDIR /build

RUN apk add --no-cache gcc musl-dev libffi-dev \
    && pip install --no-cache-dir --upgrade pip wheel

COPY requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /wheels -r requirements.txt

# ---- runtime ----
FROM python:3.12-alpine AS runtime

WORKDIR /app

RUN apk add --no-cache libffi \
    && adduser -D -u 1000 deli

COPY --from=builder /wheels /wheels
COPY requirements.txt pyproject.toml ./
COPY deli/ deli/
COPY examples/ /app/examples/

RUN pip install --no-cache-dir /wheels/* \
    && pip install --no-cache-dir . \
    && rm -rf /wheels \
    && chown -R deli:deli /app

USER deli

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["python", "-m", "deli"]
CMD ["--help"]

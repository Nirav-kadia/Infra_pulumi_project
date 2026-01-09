FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code

# Install Python dependencies
COPY requirements.txt /code/
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# Copy project
COPY . /code/

# Ensure entrypoint is executable
RUN if [ -f /code/docker/entrypoint.sh ]; then chmod +x /code/docker/entrypoint.sh; fi

EXPOSE 8080

ENTRYPOINT ["/code/docker/entrypoint.sh"]

CMD ["gunicorn", "demo_project.wsgi:application", "--bind", "0.0.0.0:8080"]

# Multi-stage Dockerfile for Django SSR (builder + slim runtime)
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System deps for building wheels and postgres client
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
    curl \
  && rm -rf /var/lib/apt/lists/*

# Copy requirements (place requirements.txt next to this Dockerfile)
COPY requirements.txt ./

# Install Python packages into /install to keep runtime slim
RUN pip install --upgrade pip setuptools wheel \
 && pip install --prefix=/install --no-cache-dir -r requirements.txt

# Copy project source
COPY . .

# Runtime image
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Create non-root user
RUN groupadd --system app && useradd --system --gid app --create-home --home-dir /home/app app

# Copy installed packages and project
COPY --from=builder /install /usr/local
COPY --from=builder /app /app

RUN mkdir -p /vol/static && chown -R app:app /app /vol

ENV PATH=/usr/local/bin:$PATH

# Make entrypoint executable if present
RUN [ -f /app/docker/entrypoint.sh ] && chmod +x /app/docker/entrypoint.sh || true

USER app

EXPOSE 8080

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "demo_project.wsgi:application", "--bind", "0.0.0.0:8080", "--workers", "3"]

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd --system --uid 10001 app && mkdir -p /app/data && chown -R app /app/data
USER app

EXPOSE 8000
# --proxy-headers: the real client IP (for the rate limiter) comes from the reverse proxy in front.
# --no-access-log: the web page may be opened once with ?key=..., which must not be written to logs.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log"]

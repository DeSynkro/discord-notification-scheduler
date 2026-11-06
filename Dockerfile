FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN addgroup --system --gid 1001 app && \
    adduser --system --uid 1001 --gid 1001 --disabled-password --no-create-home app && \
    mkdir -p /app/data && \
    chown -R app:app /app && \
    chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 9001

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9001", "--workers", "1"]

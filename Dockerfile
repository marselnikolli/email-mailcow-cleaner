FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-26.1.4.tgz -o /tmp/docker.tgz \
    && tar -xzf /tmp/docker.tgz -C /usr/local/bin --strip-components=1 docker/docker \
    && rm /tmp/docker.tgz

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

VOLUME /app/data

EXPOSE 5000

ENV FLASK_ENV=production
ENV DATA_DIR=/app/data

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--access-logfile", "-", "app.main:app"]

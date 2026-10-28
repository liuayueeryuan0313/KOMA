FROM node:24-bookworm-slim AS node
FROM python:3.12-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data HOST=0.0.0.0 PORT=8080 NODE_BIN=/usr/local/bin/node
LABEL org.opencontainers.image.title="KOMA" org.opencontainers.image.version="0.4.3" org.opencontainers.image.authors="安稳" org.opencontainers.image.url="https://github.com/liuayueeryuan0313"
WORKDIR /app
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 komama \
    && useradd --uid 10001 --gid 10001 --no-create-home komama \
    && mkdir /data && chown komama:komama /data
COPY --chown=komama:komama . .
ARG KOMA_BUILD_DATE
RUN python -c "from koma.app_version import write_build_info; write_build_info()"
USER komama
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"
CMD ["python", "server.py"]

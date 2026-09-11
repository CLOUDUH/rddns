FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 RDDNS_DATA_DIR=/data
WORKDIR /app
COPY requirements.txt ./
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r requirements.txt \
    && useradd --uid 10001 --create-home app \
    && mkdir /data && chown app:app /data
COPY rddns_web ./rddns_web
USER app
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
 CMD python -c "import os, urllib.request; h=os.getenv('RDDNS_HOST','127.0.0.1'); p=os.getenv('RDDNS_PORT','8080'); urllib.request.urlopen('http://'+h+':'+p+'/healthz', timeout=3)"
CMD ["python", "-m", "rddns_web.app"]

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN (pip install --no-cache-dir --retries 1 --timeout 20 --index-url https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt \
    || pip install --no-cache-dir --retries 1 --timeout 20 --index-url https://pypi.org/simple -r requirements.txt) \
    && useradd --uid 10001 --create-home app \
    && mkdir /data && chown app:app /data
COPY rddns_web ./rddns_web
USER app
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
 CMD python -c "import os, urllib.request; p=os.getenv('PORT','8080'); urllib.request.urlopen('http://127.0.0.1:'+p+'/healthz', timeout=3)"
CMD ["python", "-m", "rddns_web.app"]

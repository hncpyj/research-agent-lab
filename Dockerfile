# The application: FastAPI, the single-page UI, and the research pipeline.
#
# The public site (web/) is not in here. It is static files and belongs on a
# CDN; this image is the part that has to stay up for hours, hold websockets
# open and write to a disk.
#
# Everything that must survive a deploy lives under DATA_DIR, which has to be a
# mounted volume: the database, the backups, the key that decrypts stored API
# keys. With no volume, a restart silently starts an empty product.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data \
    EXPERIMENTS_DIR=/data/experiments \
    HOSTED=1

WORKDIR /app

# Dependencies first, so a code change does not reinstall them.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agents ./agents
COPY memory ./memory
COPY models ./models
COPY tools ./tools
COPY ui ./ui
COPY config.py router.py run_ui.py main.py ./

RUN mkdir -p /data && useradd --create-home --uid 10001 researcher && chown -R researcher /data /app
USER researcher

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health').read()"

# The host decides the port; uvicorn is started through run_ui.py so the
# proxy-header handling and the refusal to bind a public address without a
# token both stay in one place.
CMD ["sh", "-c", "python run_ui.py --host 0.0.0.0 --port ${PORT:-8000} --no-browser"]

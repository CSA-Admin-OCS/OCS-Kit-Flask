# OCS Kit Flask backend. Runtime needs Python only: code execution goes to the code_runner
# container (CODE_RUNNER=remote), and every requirement ships as a wheel, so there is no
# nodejs, npm, git or compiler here.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first for layer caching
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.txt

COPY . /app

# Code stays root-owned and read-only; only instance/ (data, usually a bind mount) is writable.
# defaults/ keeps files that a bind mount over instance/ would otherwise hide (see entrypoint.sh).
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin appuser && \
    sed -i 's/\r$//' entrypoint.sh && \
    mkdir -p defaults instance/volumes instance/uploads instance/data && \
    cp -r instance/uploads defaults/uploads && \
    chmod -R a+rX,go-w /app && \
    chmod 555 entrypoint.sh && \
    chown -R appuser:appuser instance

ENV FLASK_ENV=production \
    HOME=/tmp \
    CODE_RUNNER=remote \
    GUNICORN_CMD_ARGS="--workers=5 --threads=2 --bind=0.0.0.0:8587 --timeout=30 --access-logfile -"

USER 1000:1000

EXPOSE 8587

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8587/login', timeout=4)"]

# Initialize the database on first boot, then start Gunicorn
ENTRYPOINT ["/app/entrypoint.sh"]

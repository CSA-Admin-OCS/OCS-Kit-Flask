# Socket.IO leaderboard server (eventlet).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp \
    FLASK_ENV=production

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.txt && \
    useradd --uid 1000 --create-home --shell /usr/sbin/nologin appuser

COPY socket_server.py /app/socket_server.py

USER 1000:1000

EXPOSE 8500

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8500/socket.io/?EIO=4&transport=polling', timeout=4)"]

CMD ["python", "socket_server.py"]

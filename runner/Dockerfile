# Runs untrusted student code (Python and JavaScript), standard library only.
FROM python:3.12-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp

WORKDIR /app

RUN apk add --no-cache nodejs && \
    adduser -D -u 1000 -s /sbin/nologin runner

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.txt

COPY runner.py /app/runner.py

USER 1000:1000

EXPOSE 8591

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import socket; socket.create_connection(('127.0.0.1', 8591), 3).close()"]

CMD ["gunicorn", "--bind", "0.0.0.0:8591", "--workers", "2", "runner:runner"]

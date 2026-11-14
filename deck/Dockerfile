# Plimsoll Deck - RF gun gateway. Standard library only, so there is no
# dependency stage and nothing to install.
FROM python:3.12-slim

WORKDIR /app
COPY app.py .

RUN useradd --system --uid 1001 harbour
USER 1001

EXPOSE 5555

# TCP, not HTTP - there is no /health to curl. Opening a socket is the only
# honest check, and it is also exactly what a scanner does.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import socket,sys; s=socket.create_connection(('127.0.0.1',5555),2); s.close()" || exit 1

CMD ["python", "app.py"]

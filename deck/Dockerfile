# Plimsoll Deck - RF gun gateway. Standard library only, so there is no
# dependency stage and nothing to install.
FROM python:3.12-slim

# Apply the base image's outstanding security patches.
#
# WHY THIS EXISTS. On 2026-11-14 Trivy failed every image at once: 12 HIGH and
# 1 CRITICAL in web, 2 HIGH in each Python image. All had fixes published
# upstream and none had reached the base image tag yet. A CVE with an
# available patch is not something to add to .trivyignore.
#
# THE COST, STATED. This breaks build reproducibility. The same Dockerfile at
# the same commit produces different packages on different days, because the
# distribution's package index moves. That is a genuine trade: patched beats
# reproducible for a runtime image, and the image digest recorded by the
# pipeline is still exact.
#
# THE BETTER ANSWER, NOT DONE. Pin the base image by digest and bump it
# deliberately when a scan says to, with Renovate or Dependabot raising the
# PR. Then patching is a reviewed commit rather than a side effect of the
# clock.
RUN apt-get update && apt-get upgrade -y \
 && rm -rf /var/lib/apt/lists/*

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

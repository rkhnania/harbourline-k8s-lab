# ---- Stage 1: build dependencies ----
FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
# --only-binary=:all: refuses source distributions.
#
# Without it, pip may fall back to an sdist and run its setup.py during the
# build - arbitrary code from a package index, executing inside the image,
# with network access. Wheels are data; sdists are programs.
#
# The cost is real: a dependency with no wheel for this platform fails the
# build instead of silently compiling. That is the trade, and failing is the
# better half of it.
RUN pip install --no-cache-dir --only-binary=:all: --prefix=/install -r requirements.txt

# ---- Stage 2: runtime ----
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

COPY --from=builder /install /usr/local

COPY app.py .

RUN useradd --system --uid 1001 harbour
USER 1001

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/health', timeout=2).status==200 else 1)"

CMD ["python", "app.py"]

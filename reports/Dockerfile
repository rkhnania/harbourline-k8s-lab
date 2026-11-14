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

WORKDIR /app

COPY --from=builder /install /usr/local

COPY app.py .

RUN useradd --system --uid 1001 harbour
USER 1001

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/health', timeout=2).status==200 else 1)"

CMD ["python", "app.py"]

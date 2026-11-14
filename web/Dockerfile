FROM nginxinc/nginx-unprivileged:alpine

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
# This image drops to uid 101 in its own Dockerfile, so apk needs root back
# for the upgrade and the USER below restores it.
USER root
RUN apk upgrade --no-cache

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html

# The base image nginxinc/nginx-unprivileged already runs as uid 101 - this
# makes it explicit. Trivy DS-0002 reads only THIS Dockerfile and cannot see
# the base image's USER, so without this the image is reported as running as
# root when it never was. Stating it is better than an exception: it documents
# the contract and survives a base image change.
USER 101

EXPOSE 8080

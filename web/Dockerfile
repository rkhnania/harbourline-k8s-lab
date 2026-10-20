FROM nginxinc/nginx-unprivileged:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html

# The base image nginxinc/nginx-unprivileged already runs as uid 101 - this
# makes it explicit. Trivy DS-0002 reads only THIS Dockerfile and cannot see
# the base image's USER, so without this the image is reported as running as
# root when it never was. Stating it is better than an exception: it documents
# the contract and survives a base image change.
USER 101

EXPOSE 8080

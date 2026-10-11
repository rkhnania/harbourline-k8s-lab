# Architecture

## Runtime topology

Generated from the live cluster with `tools/kubectl-topology`:

```mermaid
flowchart LR
  client([Internet])
  ing_harbourline[["Ingress harbourline.localtest.me"]]
  client --> ing_harbourline
  ing_harbourline -->|"/reports"| svc_harbourline_reports
  ing_harbourline -->|"/"| svc_harbourline_web
  svc_harbourline_api(["Svc harbourline-api:8080"])
  wl_harbourline_api["Deployment harbourline-api<br/>3/3 ready"]
  svc_harbourline_api --> wl_harbourline_api
  svc_harbourline_db(["Svc harbourline-db:5432 (headless)"])
  wl_harbourline_db["StatefulSet harbourline-db<br/>1/1 ready"]
  svc_harbourline_db --> wl_harbourline_db
  svc_harbourline_reports(["Svc harbourline-reports:8080"])
  wl_harbourline_reports["Deployment harbourline-reports<br/>2/2 ready"]
  svc_harbourline_reports --> wl_harbourline_reports
  svc_harbourline_web(["Svc harbourline-web:80"])
  wl_harbourline_web["Deployment harbourline-web<br/>2/2 ready"]
  svc_harbourline_web --> wl_harbourline_web
```

> Service-to-service edges (web -> api, api -> db) are deliberately absent.
> They exist in nginx.conf and the ConfigMap, not in any Kubernetes object,
> so the API server cannot report them.

## Delivery pipeline

```mermaid
flowchart LR
  dev([Developer]) -->|push| gh[GitHub]
  gh --> build[CI: buildx matrix<br/>api, web, reports]
  gh --> scan[CI: Trivy<br/>fs, config, image]
  build -->|push image| ghcr[(GHCR)]
  build --> deploy[CI: bump tag in<br/>helm values]
  scan --> deploy
  deploy -->|commit| gh
  gh -->|poll| argo[Argo CD]
  argo -->|apply| k8s[kind cluster]
  ghcr -->|imagePullSecret| k8s
```

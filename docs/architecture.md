# 🏗️ Architecture

## ☸️ Runtime topology

Generated from the **live cluster** by [`tools/kubectl-topology`](../tools/kubectl-topology) — a kubectl plugin that matches Service selectors against pod-template labels, so every edge shown is one the cluster itself would route.

```mermaid
flowchart LR
  internet(["🌐 Internet"])

  subgraph ns["☸️  namespace: harbourline"]
    direction LR
    ing_harbourline[["🚪 Ingress<br/>harbourline.localtest.me"]]
    svc_harbourline_api(["🔀 harbourline-api<br/>:8080"])
    wl_harbourline_api["🚀 harbourline-api<br/>Deployment<br/>🟢 3/3 ready"]
    svc_harbourline_db(["🧭 harbourline-db<br/>:5432<br/><i>headless</i>"])
    wl_harbourline_db["🗄️ harbourline-db<br/>StatefulSet<br/>🟢 1/1 ready"]
    svc_harbourline_reports(["🔀 harbourline-reports<br/>:8080"])
    wl_harbourline_reports["🚀 harbourline-reports<br/>Deployment<br/>🟢 2/2 ready"]
    svc_harbourline_web(["🔀 harbourline-web<br/>:80"])
    wl_harbourline_web["🚀 harbourline-web<br/>Deployment<br/>🟢 2/2 ready"]
  end

  ing_harbourline -->|"/"| svc_harbourline_web
  ing_harbourline -->|"/reports"| svc_harbourline_reports
  internet ==> ing_harbourline
  svc_harbourline_api --> wl_harbourline_api
  svc_harbourline_db --> wl_harbourline_db
  svc_harbourline_reports --> wl_harbourline_reports
  svc_harbourline_web --> wl_harbourline_web

  classDef ing  fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#78350f
  classDef svc  fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#1e3a8a
  classDef hsvc fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#4c1d95
  classDef wl   fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#14532d
  classDef sts  fill:#ffe4e6,stroke:#e11d48,stroke-width:2px,color:#881337
  class ing_harbourline ing
  class svc_harbourline_api,svc_harbourline_reports,svc_harbourline_web svc
  class svc_harbourline_db hsvc
  class wl_harbourline_api,wl_harbourline_reports,wl_harbourline_web wl
  class wl_harbourline_db sts
```

> ⚠️ **What this diagram cannot show.** There are no `web → api` or `api → db` edges, because those dependencies live in `nginx.conf` and a ConfigMap — not in any Kubernetes object. The API server does not know they exist. Observing them needs eBPF tooling or a service mesh.

## 🚚 Delivery pipeline

```mermaid
flowchart LR
  dev(["👩‍💻 Developer"]) ==>|git push| gh
  subgraph ci["⚙️ GitHub Actions"]
    direction TB
    build["🔨 Build matrix<br/>api · web · reports"]
    scan["🛡️ Trivy<br/>image · fs · config"]
    bump["🏷️ Bump tags in<br/>helm values"]
    build --> bump
    scan --> bump
  end
  gh[("🐙 GitHub<br/>main")] --> build
  gh --> scan
  build -->|push image| ghcr[("📦 GHCR")]
  bump ==>|commit| gh
  gh ==>|poll / webhook| argo{{"🐙 Argo CD"}}
  argo ==>|apply| k8s["☸️ kind cluster<br/>harbourline"]
  ghcr -.->|imagePullSecret| k8s

  classDef src fill:#e0e7ff,stroke:#4f46e5,stroke-width:2px,color:#312e81
  classDef sec fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#7f1d1d
  classDef art fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#78350f
  classDef run fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#14532d
  class dev,gh src
  class scan sec
  class ghcr,bump,build art
  class argo,k8s run
```

**No cluster credentials exist in CI.** The pipeline only ever writes to Git; Argo CD pulls. That is the security property GitOps buys you.

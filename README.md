# Harbourline Logistics — Container & Kubernetes Lab

Hands-on lab environment: containerising a shipment-tracking API, then running it
on Kubernetes and AWS EKS.

## Structure

- `api/` — Python/Flask shipment tracking API and its Dockerfile

## API endpoints

| Endpoint | Purpose |
|---|---|
| `/health` | Liveness check; returns hostname and environment |
| `/config` | Non-sensitive configuration currently in effect |
| `/dbcheck` | Verifies PostgreSQL connectivity and row count |

## Running locally

```bash
docker network create harbour-net
docker volume create hl-pgdata
docker run -d --name hl-db --network harbour-net \
  -e POSTGRES_PASSWORD=changeme \
  -v hl-pgdata:/var/lib/postgresql/data postgres:16-alpine
docker build -t harbourline/api:latest ./api
docker run -d --name hl-api --network harbour-net -p 8080:8080 \
  --env-file api/db.env harbourline/api:latest
```

`api/db.env` holds credentials and is intentionally not committed. See `api/db.env.example`.

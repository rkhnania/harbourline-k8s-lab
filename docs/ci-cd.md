# CI/CD pipeline

`.github/workflows/ci.yaml`. Every stage can refuse; nothing here is advisory.

```
test ──> sonar ──> build ──> deploy
scan ─────────────────────> deploy
```

| Job | Does | Fails when |
|---|---|---|
| `test` | pytest for `api` and `reports`, against a real Postgres service container | any test fails |
| `sonar` | SonarCloud analysis + quality gate | the gate fails |
| `scan` | Trivy filesystem (deps + secrets) and config (Dockerfiles + manifests) | any CRITICAL/HIGH, or MEDIUM in config |
| `build` | builds each image, scans it, pushes to GHCR | any CRITICAL/HIGH in the image |
| `deploy` | rewrites the image tag in the three Helm values files and commits | — |

`web` is not in the `test` matrix: it is nginx serving a static file.

## Triggers

- **push to `main`** on `api/**`, `web/**`, `reports/**`, `.github/workflows/ci.yaml`
- **pull_request to `main`** on the same paths
- `workflow_dispatch`

`deploy` carries `if: github.event_name == 'push'`, and the GHCR login and push
steps do too. **A pull request builds and scans but never publishes or deploys.**

The `deploy` job commits to `helm/**`, which is **not** in `on.push.paths`, so
CI does not retrigger itself. That exclusion is load-bearing — do not add
`helm/**` to the paths list.

## Why the pipeline holds no cluster credentials

The last step is a **commit** that bumps an image tag. Argo CD notices and pulls.
Nothing in CI can reach a cluster, so a compromised runner cannot either. Keep it
that way: resist the temptation to add a `kubectl apply` step.

## Required configuration

| Secret | Where | Purpose |
|---|---|---|
| `SONAR_TOKEN` | repo secret | SonarCloud analysis. A **User Token** from https://sonarcloud.io/account/security |
| `GITHUB_TOKEN` | automatic | GHCR push, and the deploy commit |

Set it without putting the value in your shell history:

```
gh secret set SONAR_TOKEN --repo rkhnania/harbourline-k8s-lab
```

Non-secret configuration lives in `sonar-project.properties` — project key and
organization are both public, visible in the SonarCloud URL.

**SonarCloud: Automatic Analysis must be OFF.** SonarCloud refuses CI analysis
while it is enabled. Administration -> Analysis Method.

## Permissions

`permissions: {}` at the workflow level — deny by default. Each job declares its
minimum:

```
test    contents: read
scan    contents: read
sonar   contents: read
build   contents: read, packages: write
deploy  contents: write
```

This matters because third-party actions execute inside these jobs with whatever
token the job holds.

## Versions are pinned to commit SHAs

Every `uses:` is a 40-character SHA with the version as a trailing comment, and
the runner is `ubuntu-24.04` rather than `ubuntu-latest`.

**A tag is a mutable label.** The owner can re-point `v4` or even `v0.36.0`, and
every workflow runs the new code on its next run. A SHA cannot be re-pointed.

Resolve one with:

```
gh api repos/<owner>/<repo>/commits/<tag> --jq .sha
```

**The cost:** SHA pins never update themselves, so you trade "runs unreviewed
code silently" for "misses security patches silently". Dependabot is the
counterpart and is not yet configured.

## Accepted exceptions

Trivy: `.trivyignore`, each entry with a rationale and a review date.
SonarCloud: marked **Accepted** in the UI, pointing at `docs/security-decisions.md`.

Both halves matter. Suppressing only in the tool hides the reasoning from anyone
reading the repository; documenting only in the repository leaves the gate
failing forever on findings that were deliberately accepted.

## Running the checks locally

Tests, in the runtime the images ship — your shell's Python is probably a
different minor version, and a failure caused by that tells you nothing:

```
docker network create hl-test
docker run -d --rm --name hl-test-db --network hl-test -e POSTGRES_PASSWORD=postgres postgres:16-alpine
docker run --rm --network hl-test -e TEST_DB_HOST=hl-test-db -e TEST_DB_PASSWORD=postgres \
  -v "$PWD/api:/app" -w /app python:3.12-slim \
  sh -c "pip install -q -r requirements.txt -r requirements-dev.txt && python -m pytest -v"
```

Without a reachable database the integration tests **skip by name** rather than
fail, so the unit tests still run on a laptop with nothing started.

Scanners, with the same flags the workflow uses:

```
docker run --rm -v "$PWD:/src" -w /src aquasec/trivy:latest fs --scanners vuln,secret --severity CRITICAL,HIGH --ignore-unfixed .
docker run --rm -v "$PWD:/src" -w /src aquasec/trivy:latest config --severity CRITICAL,HIGH,MEDIUM --skip-dirs helm .
```

## Troubleshooting

**`Not authorized` from the Sonar scanner** — `SONAR_TOKEN` is missing, wrong, or
is a project token for a different project. Note that a *public* project lets an
unauthenticated scanner read settings and resolve the project key before failing
at "Create analysis": getting that far proves nothing about the token.

**`You are running CI analysis while Automatic Analysis is enabled`** — the
SonarCloud toggle above. It refuses rather than picking one, correctly: two
analysis sources would overwrite each other and the gate would reflect whichever
ran last.

**The quality gate passes but the code is not clean.** "Sonar way" judges **new
code** only. A green gate means *you did not make it worse*, not *this is good*.
Overall-code ratings are on the project Summary page under "Overall Code".

**`git pull --ff-only` refuses with "Not possible to fast-forward"** — the
`deploy` job pushed its tag-bump commit to `main`, so your branch diverged. Use
`git pull --rebase`. Rebase what is local; merge what is shared.

**A Trivy finding you believe is wrong** — check whether it is reading something
you do not deploy. Trivy renders Helm charts with their *default* values, and it
reads only the Dockerfile in front of it, so it cannot see a base image's `USER`.

**A test fails only in CI** — compare the Python version. CI pins 3.12 to match
the images; your shell may be newer.

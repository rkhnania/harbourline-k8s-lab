# A WMS topology, translated to Kubernetes

Harbourline Logistics is a warehouse operation, and warehouse systems have a
shape. This document takes a conventional tier-3 WMS architecture — the Blue
Yonder/MOCA pattern: a Portal tier, a middleware tier, Oracle RAC with Data
Guard, RF guns reaching it through terminal emulation — and works out what it
becomes on Kubernetes.

**The useful part is not the mapping. It is the mismatches.** Three of these
tiers translate almost directly. One does not translate at all, and saying so
plainly is more valuable than a diagram where everything fits.

| WMS tier | Kubernetes | State |
|---|---|---|
| Portal, active/active, sticky | Deployment + ingress cookie affinity | **built** |
| MOCA middleware, non-sticky | stateless Deployments, round-robin | **built** |
| Two sites, active/active | topology spread constraints | partial |
| Oracle RAC | — | **does not translate** |
| Data Guard | async replica in another failure domain | not built |
| Archive | separate retention store | not built |
| RF guns via StayLinked | long-lived TCP, not L7 | not built |
| EMS | Prometheus + Alertmanager | built, **alerts nothing** |

---

## Portal tier — sticky sessions

Built 2026-11-14. The interesting part was getting it wrong first, on purpose,
and measuring.

### The obvious answer, and why it fails

Kubernetes Services offer exactly one session affinity: `sessionAffinity:
ClientIP`. It hashes the source IP of the connection reaching the Service and
pins it to one endpoint.

Set on the api Service, with three api pods and two web pods, ten requests
produced:

    5  harbourline-api-...-c2mcm
    5  harbourline-api-...-p8fgh

**Not one pod** — so it did not pin a user. **Not three** — so affinity was
working. **Two**, because a Service sees the source IP of whatever opened the
connection, and behind a proxy that is the proxy. It pinned per nginx pod.

The second finding was not the one being tested: the third api pod received
**nothing**. A third of the capacity went idle, silently, with no event and no
alert. Affinity at the wrong layer does not merely fail to pin users — it
strands capacity, and the failure is invisible.

> A Service is L4. It cannot see a session, because a session is an L7 idea.
> Asking it for sticky sessions gets you sticky *connections*, which is a
> different thing wearing the same word.

### The correct answer

Cookie affinity at the ingress — which is exactly where the WMS diagram puts
it: on the load balancers facing users, with the tier-to-tier traffic marked
non-sticky.

```
nginx.ingress.kubernetes.io/affinity: "cookie"
nginx.ingress.kubernetes.io/session-cookie-name: "harbourline-portal"
nginx.ingress.kubernetes.io/session-cookie-max-age: "28800"
nginx.ingress.kubernetes.io/affinity-mode: "balanced"
```

Verified: `Set-Cookie: harbourline-portal=...; Max-Age=28800; HttpOnly`, and
all three api pods back in rotation behind it.

**`balanced`, not `persistent`.** `persistent` keeps every existing session
exactly where it is, which sounds safer and means a scale-out relieves nothing
until sessions expire. Add pods during a peak and the new ones idle while the
hot ones stay hot — and with a shift-length cookie, that is the whole shift.

**The cookie is sized to a warehouse shift.** Eight hours, because the cost of
a moved session is an operator losing their working context mid-task. That is
an operational constraint, not a technical one, and it is the sort of number
that should come from the business rather than from a default.

### Debt

The cookie carries `HttpOnly` but not `Secure` or `SameSite`, because this
cluster serves HTTP. A session cookie identifying a logged-in operator for
eight hours should not travel in clear text. Fixing it means TLS on the kind
cluster, and then `session-cookie-secure: "true"`.

### The deeper point

**Sticky sessions are a constraint inherited from an application that keeps
state in memory, not a feature.** Every one costs something: uneven load,
sessions lost on a rolling update, capacity that cannot be used. The question
to ask before implementing stickiness is whether the application could keep its
session state in Redis or a signed cookie instead — because then it needs none
of this.

Legacy WMS portals usually cannot. That is a real constraint and worth
modelling honestly. It is not an argument for making new services sticky.

---

## Oracle RAC — the tier that does not translate

Stated plainly because the honest answer matters more than a complete diagram.

RAC is **shared-everything** clustering: several instances mounting the *same*
storage simultaneously, coordinating through a cache fusion interconnect.
Kubernetes storage is the opposite by design — a volume is attached to one node
at a time (`ReadWriteOnce`), and the whole scheduling model assumes a pod can
be killed and rescheduled elsewhere.

You can run Oracle on Kubernetes. You cannot reproduce RAC's properties with a
StatefulSet and a PVC, and a design that claims to has usually swapped RAC for
primary/replica failover without saying so.

The honest options:

- **Leave the database where it is.** Containerise the application tiers, keep
  RAC on its own infrastructure. Most real migrations do this, and it is not a
  failure.
- **Managed service.** RDS, Cloud SQL, Aurora — someone else's problem, and
  different availability characteristics that must be stated rather than
  assumed equivalent.
- **An operator** (CloudNativePG, Crunchy, Oracle's own). Real primary/replica
  HA with automated failover — **not** RAC. Different failure modes, different
  RPO and RTO.

What this lab has: a single Postgres StatefulSet with one replica. No HA at
all, and calling it anything else would be dishonest. See *Not built* below.

---

## Not built yet

**Data Guard → a read replica.** Streaming replication into a different
failure domain, and a documented, *performed* failover drill. By this project's
standard an untested restore is not a backup, and an untested failover is not
HA.

**Archive.** A separate retention store. The WMS pattern splits it because
operational queries and historical ones have different access patterns and
different retention rules.

**RF guns and StayLinked.** The most interesting remaining piece. Terminal
emulation holds a long-lived TCP session — not HTTP, so an L7 Ingress is the
wrong tool entirely. This needs a `LoadBalancer` Service, a NodePort, or TCP
passthrough, and the stickiness has to survive a pod restart or the operator
loses their scan mid-pick. It is the case where Kubernetes' assumptions about
disposable pods meet a protocol that assumes the opposite.

**Alerting.** Alertmanager is deployed and routes nothing. The EMS box in a WMS
diagram is not decoration — it is the thing that wakes someone when the
overnight wave does not run.

#!/usr/bin/env python3
"""
CIS Kubernetes Benchmark 5.1.7 - 5.1.13: who holds a permission that lets a
subject become more powerful than it was granted.

    python3 k8s/labs/rbac/audit-privileged-rbac.py [kube-context]

WHY THIS REPLACED THE SHELL VERSION
The first version grepped `.rules[*].resources` with no regard for verbs, so
kube-state-metrics - which holds list and watch on nearly everything and create
on nothing - was reported under "create on persistentvolumes" and under the
webhook-configuration check. Both were false. A security report that cries wolf
on a read-only role gets ignored, which is worse than not running it.

This version evaluates each rule as a whole: the apiGroup, the resource AND the
verb must all match, with `*` expanded in every position.

TWO THINGS IT DOES THAT MATTER MORE THAN THE MATCHING

1. It separates built-ins from the rest, by the label Kubernetes itself puts on
   them - kubernetes.io/bootstrapping=rbac-defaults - not by guessing from the
   name. The controller manager must mint ServiceAccount tokens; the CSR
   controller must approve CSRs. The finding is never "this permission exists",
   it is "something nobody vetted holds it".

2. It resolves bindings. An alarming ClusterRole that no binding references is
   latent, not active. The question is never "does this Role exist", it is
   "which subject actually has it", so every finding is printed with the
   bindings that confer it and the subjects they name.
"""
import json
import subprocess
import sys
from collections import defaultdict

CTX = sys.argv[1] if len(sys.argv) > 1 else "kind-harbourline"


def kget(kind):
    r = subprocess.run(
        ["kubectl", "--context", CTX, "get", kind, "-o", "json"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        sys.exit("kubectl get %s failed:\n%s" % (kind, r.stderr.strip()))
    return json.loads(r.stdout)["items"]


# id, human description, apiGroup, resources, verbs
CHECKS = [
    ("5.1.8",  "escalate on roles/clusterroles",
     "rbac.authorization.k8s.io", {"roles", "clusterroles"}, {"escalate"}),
    ("5.1.8",  "bind on roles/clusterroles",
     "rbac.authorization.k8s.io", {"roles", "clusterroles"}, {"bind"}),
    ("5.1.8",  "impersonate users/groups/serviceaccounts",
     "", {"users", "groups", "serviceaccounts"}, {"impersonate"}),
    ("5.1.9",  "create persistentvolumes",
     "", {"persistentvolumes"}, {"create"}),
    ("5.1.10", "access nodes/proxy",
     "", {"nodes/proxy"}, {"get", "create", "update", "patch", "*"}),
    ("5.1.11", "approve certificatesigningrequests",
     "certificates.k8s.io", {"certificatesigningrequests/approval"},
     {"update", "patch", "create"}),
    ("5.1.12", "write validating/mutatingwebhookconfigurations",
     "admissionregistration.k8s.io",
     {"validatingwebhookconfigurations", "mutatingwebhookconfigurations"},
     {"create", "update", "patch", "delete"}),
    ("5.1.13", "create serviceaccounts/token",
     "", {"serviceaccounts/token"}, {"create"}),
]

WHY = {
    "5.1.8": "escalate removes the guardrail that stops you creating a Role more\n"
             "powerful than your own. bind reaches the same place by attaching an\n"
             "existing powerful Role. impersonate is equivalent to holding every\n"
             "permission the impersonated identity has.",
    "5.1.9": "a PersistentVolume can mount a hostPath, so creating one is a route to\n"
             "reading any file on a node, kubelet credentials included.",
    "5.1.10": "reaches the kubelet API directly, bypassing the API server's\n"
              "authorization for exec and logs on that node.",
    "5.1.11": "approving your own CSR mints a client certificate for any identity the\n"
              "cluster CA will sign - system:masters included.",
    "5.1.12": "disables admission control, Kyverno included, or redirects it to an\n"
              "endpoint that mutates every object admitted.",
    "5.1.13": "mints a token for any ServiceAccount: lateral movement to every\n"
              "permission any workload holds.",
}


def rule_matches(rule, group, resources, verbs):
    groups = set(rule.get("apiGroups") or [])
    res = set(rule.get("resources") or [])
    vrb = set(rule.get("verbs") or [])
    if group not in groups and "*" not in groups:
        return False
    if not (res & resources) and "*" not in res:
        return False
    if not (vrb & verbs) and "*" not in vrb:
        return False
    return True


def builtin(obj):
    labels = (obj.get("metadata") or {}).get("labels") or {}
    return labels.get("kubernetes.io/bootstrapping") == "rbac-defaults"


def subject_str(s):
    kind = s.get("kind", "?")
    name = s.get("name", "?")
    ns = s.get("namespace")
    return "%s/%s%s" % (kind, name, (" in " + ns) if ns else "")


def main():
    croles = kget("clusterroles")
    roles = kget("roles")
    crbs = kget("clusterrolebindings")
    rbs = kget("rolebindings")

    # roleRef target -> list of (binding description, [subjects])
    bindings = defaultdict(list)
    for b in crbs:
        ref = b["roleRef"]
        key = (ref["kind"], ref["name"], None)
        bindings[key].append(
            ("ClusterRoleBinding/" + b["metadata"]["name"],
             [subject_str(s) for s in (b.get("subjects") or [])]))
    for b in rbs:
        ref = b["roleRef"]
        ns = b["metadata"]["namespace"]
        key = (ref["kind"], ref["name"], ns if ref["kind"] == "Role" else None)
        bindings[key].append(
            ("RoleBinding/%s in %s" % (b["metadata"]["name"], ns),
             [subject_str(s) for s in (b.get("subjects") or [])]))

    allobj = [("ClusterRole", c, None) for c in croles] + \
             [("Role", r, r["metadata"]["namespace"]) for r in roles]

    print("CIS 5.1.7 - 5.1.13   context: %s" % CTX)
    print("=" * 66)

    # ---- 5.1.7 -------------------------------------------------------------
    print("\n5.1.7  Subjects bound to cluster-admin\n")
    expected_groups = {"system:masters", "kubeadm:cluster-admins"}
    findings_517 = []
    for b in crbs:
        if b["roleRef"]["name"] != "cluster-admin":
            continue
        for s in (b.get("subjects") or []):
            ok = s.get("kind") == "Group" and s.get("name") in expected_groups
            tag = "  ok  " if ok else "FINDING"
            line = "  [%s] %-34s via %s" % (
                tag, subject_str(s), b["metadata"]["name"])
            print(line)
            if not ok:
                findings_517.append(subject_str(s))
    if findings_517:
        print("\n  system:masters bypasses RBAC entirely - the authorizer "
              "short-circuits\n  before any Role is consulted, so cluster-admin "
              "granted this way cannot\n  be narrowed, only removed.")

    # ---- 5.1.8 - 5.1.13 ----------------------------------------------------
    total_findings = len(findings_517)
    for cid, desc, group, resources, verbs in CHECKS:
        hits_builtin, hits_custom = [], []
        for kind, obj, ns in allobj:
            for rule in (obj.get("rules") or []):
                if rule_matches(rule, group, resources, verbs):
                    name = obj["metadata"]["name"]
                    label = "%s/%s%s" % (kind, name, (" in " + ns) if ns else "")
                    (hits_builtin if builtin(obj) else hits_custom).append(
                        (label, (kind, name, ns)))
                    break

        print("\n%s  %s" % (cid, desc))
        print("-" * 66)
        if not hits_custom:
            print("  no non-built-in holder   (%d built-in, expected)"
                  % len(hits_builtin))
            continue

        total_findings += len(hits_custom)
        for label, key in hits_custom:
            bound = bindings.get(key, [])
            if bound:
                print("  [FINDING] %s" % label)
                for bname, subs in bound:
                    print("            via %s" % bname)
                    for s in subs:
                        print("                -> %s" % s)
            else:
                print("  [latent ] %s   (no binding references it)" % label)
        print("\n  Why it matters: %s" % WHY[cid].replace("\n", "\n  "))
        print("  (%d built-in holder(s) not shown)" % len(hits_builtin))

    print("\n" + "=" * 66)
    print("%d finding(s) needing a human decision." % total_findings)
    print("\nNot answerable with kubectl: the reverse lookup, 'who can read")
    print("Secrets in harbourline'. auth can-i only tests a subject you name.")
    print("krew + kubectl-who-can, or rbac-tool, answers it.")


if __name__ == "__main__":
    main()

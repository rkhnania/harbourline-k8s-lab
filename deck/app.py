"""
Plimsoll Deck — the RF gun gateway.

WHAT THIS IS
Handheld scanners in a warehouse do not speak HTTP. They run terminal
emulation: one TCP connection opened at the start of a shift and held for
hours, carrying a conversation rather than a series of requests. In a
conventional WMS this is what StayLinked sits in front of.

WHY IT MATTERS HERE
Everything else in this project is stateless and disposable. A pod can die and
another serves the next request; nobody notices. This cannot work that way. The
session IS the connection, and the connection holds the operator's place in a
pick. Losing it loses their work, mid-task, on a device with no back button.

That makes Deck the tier where Kubernetes' central assumption — pods are
cattle — meets a protocol that assumes the opposite, and the interesting
engineering is in what you do about it rather than in the code below.

The session state here is deliberately in memory, because that is the honest
version of the problem. See docs/wms-architecture.md.
"""
import asyncio
import json
import os
import socket
import urllib.error
import urllib.request

PORT = int(os.environ.get("DECK_PORT", "5555"))
# 0.0.0.0 inside a container means "this pod's network namespace", not "the
# whole network" - the pod has one interface and kube-proxy decides what
# reaches it. Binding to 127.0.0.1 here would make the pod unreachable from
# its own Service. Overridable so the intent is declared rather than assumed.
BIND = os.environ.get("DECK_BIND", "0.0.0.0")  # NOSONAR - see above
API = os.environ.get("API_URL", "http://harbourline-api:8080")
HOST = socket.gethostname()
IDLE_TIMEOUT = int(os.environ.get("DECK_IDLE_TIMEOUT", "1800"))

BANNER = (
    "\r\n"
    "  PLIMSOLL DECK  —  Harbourline Logistics\r\n"
    "  gateway: {host}\r\n"
    "  LOGIN <operator> | SCAN <sku> | STOCK [sku] | LIST\r\n"
    "  MOVE <from> <to> <qty> | PICK <order> <line> [qty]\r\n"
    "  STATUS | HELP | QUIT\r\n"
    "\r\n"
)


def fetch(path):
    """Call Plimsoll Core. stdlib only - this image has no dependencies.

    Every failure becomes a message the scanner can display. An operator
    holding a handheld cannot read a stack trace and cannot retry a crashed
    gateway, so nothing here is allowed to raise.

    The exceptions are named rather than caught wholesale: `except Exception`
    hides bugs exactly as well as it handles failures, and a typo in this
    module would arrive at the scanner as "core unreachable".
    """
    try:
        with urllib.request.urlopen(f"{API}{path}", timeout=3) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"core returned {e.code}"}
    except urllib.error.URLError as e:
        return {"error": f"core unreachable: {e.reason}"}
    except json.JSONDecodeError:
        return {"error": "core returned malformed JSON"}
    except (TimeoutError, OSError) as e:
        return {"error": f"core unreachable: {type(e).__name__}"}


def post(path, payload):
    """Write to Plimsoll Core. Same discipline as fetch(): never raises.

    Core answers a refused movement with 409 and a body explaining why - not
    enough stock, over-receipt, order not picked. That body is the most useful
    thing a scanner can show, so an HTTPError is read rather than discarded.
    An operator told "core returned 409" learns nothing; one told "insufficient
    stock at source" walks to a different bay.
    """
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{API}{path}", data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except (json.JSONDecodeError, OSError):
            return {"error": f"core returned {e.code}"}
    except urllib.error.URLError as e:
        return {"error": f"core unreachable: {e.reason}"}
    except json.JSONDecodeError:
        return {"error": "core returned malformed JSON"}
    except (TimeoutError, OSError) as e:
        return {"error": f"core unreachable: {type(e).__name__}"}


class Session:
    """One operator, one shift, one connection.

    Held in memory on purpose. This is why the tier needs sticky routing and
    why a rolling update is not free: nothing outside this process knows the
    operator has scanned anything.
    """

    def __init__(self, peer):
        self.peer = peer
        self.scans = []
        self.picked = 0
        self.operator = None
        self.current_sku = None

    @property
    def actor(self):
        """What the ledger records for every movement this session makes.

        THIS IS WHERE THE IN-MEMORY SESSION BECOMES DURABLE. Everything else
        about the session dies with the pod. The actor string is written into
        movements.actor inside the same transaction as the stock change, so
        after a rolling update the only surviving evidence that gun 7 moved
        forty cartons is a row in the ledger.

        Both halves matter: the pod name answers "which gateway held the
        session", the operator answers "who was holding the gun".
        """
        return f"deck/{HOST}/{self.operator or 'anon'}"

    def scan(self, ref):
        """Scanning a barcode selects a SKU; it does not move anything.

        Real RF flows are scan-then-act for a reason: the scan confirms what is
        in the operator's hand, and the next command says what to do with it.
        Collapsing the two is how you get stock moved against the wrong SKU.
        """
        data = fetch("/skus")
        if isinstance(data, dict) and "error" in data:
            return f"ERR  {data['error']}"
        for row in data or []:
            if row.get("sku") == ref:
                self.scans.append(ref)
                self.current_sku = ref
                return (f"OK   {ref}  {row.get('description', '?')}"
                        f"  uom={row.get('uom', '?')}"
                        + ("  HAZARD=" + row["hazard_class"] if row.get("hazard_class") else ""))
        return f"ERR  {ref} not found"


def dispatch(session, raw):
    """The protocol: text in, text out. Returns (reply, close).

    Deliberately separate from the socket. asyncio.start_server is not ours to
    test; the command grammar is, and it is the part that will be wrong. A
    function with no I/O in it can be tested in microseconds without a network,
    which is the difference between a tier that has tests and one that does
    not.
    """
    parts = raw.strip().split()
    if not parts:
        return "", False

    cmd, args = parts[0].upper(), parts[1:]

    if cmd == "QUIT":
        return (f"BYE  {len(session.scans)} scans, {session.picked} picked", True)

    if cmd == "LOGIN":
        if not args:
            return "ERR  LOGIN needs an operator id", False
        session.operator = args[0]
        return f"OK   logged in as {session.operator}  actor={session.actor}", False

    if cmd == "SCAN":
        if not args:
            return "ERR  SCAN needs a sku", False
        return session.scan(args[0]), False

    if cmd == "STOCK":
        sku = args[0] if args else session.current_sku
        if not sku:
            return "ERR  scan a sku first, or give one", False
        data = fetch(f"/stock?sku={sku}")
        if "error" in data:
            return f"ERR  {data['error']}", False
        lines = data.get("lines", [])
        if not lines:
            return f"  {sku}: no stock on hand", False
        body = "\r\n".join(f"  {r['location']:<10} {r['zone']:<5} {r['qty']:>6}"
                            for r in lines[:20])
        return f"{body}\r\n  on hand: {data.get('on_hand', 0)}", False

    if cmd == "MOVE":
        # Putaway. Uses the scanned SKU rather than taking one as an argument:
        # the barcode in the operator's hand is more trustworthy than a value
        # they typed on a 12-key pad.
        if not session.current_sku:
            return "ERR  scan a sku first", False
        if len(args) != 3:
            return "ERR  MOVE needs <from> <to> <qty>", False
        try:
            qty = int(args[2])
        except ValueError:
            return f"ERR  '{args[2]}' is not a quantity", False
        res = post("/putaway", {"sku": session.current_sku, "from": args[0],
                                "to": args[1], "qty": qty, "actor": session.actor})
        if "error" in res:
            return f"ERR  {res['error']}", False
        return (f"OK   moved {res['moved']} {res['sku']}"
                f"  {res['from']} -> {res['to']}"), False

    if cmd == "PICK":
        if len(args) not in (2, 3):
            return "ERR  PICK needs <order> <line> [qty]", False
        try:
            line_no = int(args[1])
            payload = {"line_no": line_no, "actor": session.actor}
            if len(args) == 3:
                payload["qty"] = int(args[2])
        except ValueError:
            return "ERR  line and qty must be numbers", False
        res = post(f"/orders/{args[0]}/pick", payload)
        if "error" in res:
            return f"ERR  {res['error']}", False
        session.picked += res["picked"]
        where = " ".join(f"{a['location']}x{a['qty']}" for a in res.get("allocation", []))
        return (f"OK   picked {res['picked']} {res['sku']}  from {where}"
                f"  order={res['order_status']}"), False

    if cmd == "LIST":
        data = fetch("/skus")
        if isinstance(data, dict) and "error" in data:
            return f"ERR  {data['error']}", False
        if not data:
            return "  (no skus)", False
        return "\r\n".join(f"  {r['sku']}  {r.get('description', '?')}"
                            for r in data[:20]), False

    if cmd == "STATUS":
        # Prints the gateway hostname so you can SEE which pod holds the
        # session - the whole point of the exercise.
        return (f"gateway={HOST}  operator={session.operator or '-'}"
                f"  sku={session.current_sku or '-'}"
                f"  scans={len(session.scans)}  picked={session.picked}"), False

    if cmd == "HELP":
        return ("LOGIN <operator> | SCAN <sku> | STOCK [sku] | LIST | "
                "MOVE <from> <to> <qty> | PICK <order> <line> [qty] | "
                "STATUS | HELP | QUIT"), False

    return f"ERR  unknown command '{cmd}'", False


async def handle(reader, writer):  # pragma: no cover - socket plumbing
    peer = writer.get_extra_info("peername")
    session = Session(peer)
    writer.write(BANNER.format(host=HOST).encode())
    await writer.drain()

    try:
        while True:
            try:
                raw = await asyncio.wait_for(reader.readline(), timeout=IDLE_TIMEOUT)
            except asyncio.TimeoutError:
                writer.write(b"BYE  idle timeout\r\n")
                break
            if not raw:
                break

            reply, close = dispatch(session, raw.decode(errors="replace"))
            if reply:
                writer.write((reply + "\r\n").encode())
                await writer.drain()
            if close:
                break
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        writer.close()


async def main():  # pragma: no cover - socket plumbing
    server = await asyncio.start_server(handle, BIND, PORT)
    print(f"Plimsoll Deck listening on {BIND}:{PORT} as {HOST}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())

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
    "  commands: SCAN <id> | LIST | STATUS | HELP | QUIT\r\n"
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


class Session:
    """One operator, one shift, one connection.

    Held in memory on purpose. This is why the tier needs sticky routing and
    why a rolling update is not free: nothing outside this process knows the
    operator has scanned anything.
    """

    def __init__(self, peer):
        self.peer = peer
        self.scans = []

    def scan(self, ref):
        data = fetch("/shipments")
        if "error" in data:
            return f"ERR  {data['error']}"
        rows = data if isinstance(data, list) else data.get("shipments", [])
        for row in rows:
            if str(row.get("id")) == ref or row.get("reference") == ref:
                self.scans.append(ref)
                return f"OK   {ref}  status={row.get('status', '?')}  picks={len(self.scans)}"
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
        return f"BYE  {len(session.scans)} picks this session", True
    if cmd == "SCAN":
        if not args:
            return "ERR  SCAN needs a reference", False
        return session.scan(args[0]), False
    if cmd == "LIST":
        data = fetch("/shipments")
        if "error" in data:
            return f"ERR  {data['error']}", False
        rows = data if isinstance(data, list) else data.get("shipments", [])
        if not rows:
            return "  (no shipments)", False
        return "\r\n".join(
            f"  {r.get('id')}  {r.get('status', '?')}" for r in rows[:20]
        ), False
    if cmd == "STATUS":
        # Prints the gateway hostname so you can SEE which pod holds the
        # session - the whole point of the exercise.
        return f"gateway={HOST}  picks={len(session.scans)}", False
    if cmd == "HELP":
        return "SCAN <id> | LIST | STATUS | HELP | QUIT", False

    return f"ERR  unknown command '{cmd}'", False


async def handle(reader, writer):
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


async def main():
    server = await asyncio.start_server(handle, BIND, PORT)
    print(f"Plimsoll Deck listening on {BIND}:{PORT} as {HOST}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())

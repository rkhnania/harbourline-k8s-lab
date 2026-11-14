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
    """Call Plimsoll Core. stdlib only - this image has no dependencies."""
    try:
        with urllib.request.urlopen(f"{API}{path}", timeout=3) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"core returned {e.code}"}
    except Exception as e:  # noqa: BLE001 - the scanner wants a message, not a trace
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

            parts = raw.decode(errors="replace").strip().split()
            if not parts:
                continue
            cmd, args = parts[0].upper(), parts[1:]

            if cmd == "QUIT":
                writer.write(f"BYE  {len(session.scans)} picks this session\r\n".encode())
                break
            elif cmd == "SCAN" and args:
                writer.write((session.scan(args[0]) + "\r\n").encode())
            elif cmd == "LIST":
                data = fetch("/shipments")
                if "error" in data:
                    writer.write(f"ERR  {data['error']}\r\n".encode())
                else:
                    rows = data if isinstance(data, list) else data.get("shipments", [])
                    for row in rows[:20]:
                        writer.write(
                            f"  {row.get('id')}  {row.get('status', '?')}\r\n".encode()
                        )
            elif cmd == "STATUS":
                # Prints the gateway hostname so you can SEE which pod holds
                # the session - the whole point of the exercise.
                writer.write(
                    f"gateway={HOST}  picks={len(session.scans)}\r\n".encode()
                )
            elif cmd == "HELP":
                writer.write(b"SCAN <id> | LIST | STATUS | HELP | QUIT\r\n")
            else:
                writer.write(f"ERR  unknown command '{cmd}'\r\n".encode())
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        writer.close()


async def main():
    server = await asyncio.start_server(handle, "0.0.0.0", PORT)
    print(f"Plimsoll Deck listening on {PORT} as {HOST}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())

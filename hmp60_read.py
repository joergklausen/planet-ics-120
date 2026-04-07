#!/usr/bin/env python3
"""
Query a Vaisala HMP60 (RS-485) through a PLANET ICS-120 serial device server in TCP Server mode.

This script opens a raw TCP socket to the ICS-120’s Port 1 TCP listener and issues Vaisala HMP60
ASCII commands (terminated by carriage return, CR = ``\\r``). It is designed for the common
deployment where:

- The HMP60 is wired to the ICS-120 serial Port 1 configured as RS-485-2W.
- The ICS-120 is configured in “TCP Server” mode (raw TCP tunnel to the serial port).
- The HMP60 is in STOP serial mode (no continuous output).

The script is robust to TCP packetization and leftover prompt bytes by:
- flushing any pending input before each command, and
- reading until the socket is idle (rather than assuming one ``recv()`` returns a full reply).

Measurement retrieval strategy:
1) Try ``SEND`` (one-shot output in STOP mode).
2) If no measurement line is seen, try ``SEND <address>`` using the configured address.
3) If needed (POLL-style access), try ``OPEN <address>``, then ``SEND``, then ``CLOSE``.

The HMP60 address is typically discoverable from the ``SERI`` / poll information output
(e.g., "Address : 5"). If you are unsure, you can try the default ``--address 0`` or inspect
the device with a manual terminal session by sending ``?`` and ``VERS``.

Example:
    One-shot read via an ICS-120 at 192.168.0.100 exposing Port 1 on TCP 5004
    (HMP60 address 5):

        python hmp60_read.py --host 192.168.0.100 --port 5004 --address 5

Output:
    The script prints the raw responses to key identification commands and prints a parsed
    measurement dict when it finds a line that looks like:

        T=  19.30 'C RH=  27.26 %RH Td=  -0.02 'C

    Parsed measurement example:

        {'T_C': 19.3, 'RH_percent': 27.26, 'Td_C': -0.02}
"""
from __future__ import annotations

import argparse
import re
import socket
import time
from typing import Optional

MEAS_RE = re.compile(
    r"T=\s*(?P<T>-?\d+(?:\.\d+)?)\s*'C"
    r".*?RH=\s*(?P<RH>-?\d+(?:\.\d+)?)\s*%RH"
    r"(?:.*?Td=\s*(?P<Td>-?\d+(?:\.\d+)?)\s*'C)?",
    re.IGNORECASE | re.DOTALL,
)

def read_until_idle(sock: socket.socket, *, total_timeout: float = 2.0, idle_timeout: float = 0.25) -> bytes:
    """Read bytes until no new data arrives for `idle_timeout` or until `total_timeout`."""
    sock.settimeout(idle_timeout)
    buf = bytearray()
    end = time.time() + total_timeout
    while time.time() < end:
        try:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf.extend(chunk)
            # keep going until we hit idle_timeout without new data
        except socket.timeout:
            break
    return bytes(buf)

def flush(sock: socket.socket) -> None:
    """Drain any pending bytes."""
    _ = read_until_idle(sock, total_timeout=0.5, idle_timeout=0.1)

def send_cmd(sock: socket.socket, cmd: str, *, total_timeout: float = 2.0) -> str:
    flush(sock)
    sock.sendall((cmd + "\r").encode("ascii", errors="ignore"))
    data = read_until_idle(sock, total_timeout=total_timeout, idle_timeout=0.25)
    return data.decode("latin-1", errors="replace").strip()

def extract_measurement(text: str) -> Optional[dict]:
    m = MEAS_RE.search(text)
    if not m:
        return None
    out = {"T_C": float(m.group("T")), "RH_percent": float(m.group("RH"))}
    if m.group("Td") is not None:
        out["Td_C"] = float(m.group("Td"))
    return out

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", required=True, type=int)
    ap.add_argument("--address", type=int, default=5, help="HMP60 address to try (from SERI/?? output).")
    args = ap.parse_args()

    with socket.create_connection((args.host, args.port), timeout=3.0) as s:
        s.settimeout(1.0)

        # Wake up prompt (optional)
        for _ in range(3):
            s.sendall(b"\r")
            time.sleep(0.05)
        flush(s)

        # Helpful info
        print("?", send_cmd(s, "?"))
        print("VERS:", send_cmd(s, "VERS"))

        # Try SEND in STOP mode (should output once)  :contentReference[oaicite:2]{index=2}
        for attempt in [
            "SEND",
            f"SEND {args.address}",
            f"OPEN {args.address}",
            "SEND",
            "CLOSE",
        ]:
            resp = send_cmd(s, attempt)
            if resp:
                print(f"\n>> {attempt}\n{resp}")

            meas = extract_measurement(resp)
            if meas:
                print("\nParsed measurement:", meas)
                return 0

        print("\nNo measurement line found.")
        print("Next checks:")
        print("- Try swapping RS-485 polarity (white/black) if you ever get only prompts but never measurements.")
        print("- If sensor is in RUN mode, stop it with 'S' first, then 'SEND'.")
        print("- Try '??' (POLL info) to confirm addressing.")
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
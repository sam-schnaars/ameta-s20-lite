"""Find out how to start the drone's video stream. Read-only: sends NO flight commands.

    python3 examples/video_probe.py

Tries:
  A) TCP 7060: send the stream request, listen 4 s
  B) TCP 8060 handshake the Mac app did (cmd 0x04 with unix time, cmd 0x06), then A again
Paste the whole output to Claude.
"""
import collections, socket, struct, time

IP = "192.168.0.1"
MAGIC = b"lewei_cmd\x00"


def header(cmd, sub=0, length=0):
    h = bytearray(46)
    h[0:10] = MAGIC
    h[10], h[11] = cmd, sub
    h[22:26] = length.to_bytes(4, "little")
    return bytes(h)


def summarize(buf):
    kinds = collections.Counter()
    i = buf.find(MAGIC)
    while i >= 0 and i + 46 <= len(buf):
        kinds[f"cmd {buf[i + 10]:02x} sub {buf[i + 11]:02x}"] += 1
        i = buf.find(MAGIC, i + 46)
    return dict(kinds)


def listen_7060(label, seconds=4):
    print(f"\n== {label}")
    try:
        s = socket.create_connection((IP, 7060), timeout=3)
    except OSError as e:
        print("  connect 7060 failed:", e)
        return
    s.settimeout(0.3)
    s.sendall(header(0x01))
    s.sendall(header(0x02))   # start video (from capture 11_connect)
    got, t0, last = bytearray(), time.time(), time.time()
    while time.time() - t0 < seconds:
        try:
            d = s.recv(65536)
            if not d:
                print("  drone closed the connection")
                break
            got += d
        except socket.timeout:
            pass
        if time.time() - last > 1:
            s.sendall(header(0x01))
            last = time.time()
    s.close()
    print(f"  received {len(got)} bytes; messages: {summarize(got)}")
    print(f"  first bytes: {bytes(got[:96]).hex()}")


def handshake_8060():
    print("\n== 8060 handshake")
    for cmd, payload in ((0x04, struct.pack("<II", int(time.time()), 0)), (0x06, b"")):
        try:
            s = socket.create_connection((IP, 8060), timeout=3)
            s.settimeout(1.5)
            s.sendall(header(cmd, 0, len(payload)) + payload)
            try:
                r = s.recv(4096)
            except socket.timeout:
                r = b""
            s.close()
            print(f"  cmd {cmd:02x}: reply {len(r)} bytes {r[:80].hex()}")
        except OSError as e:
            print(f"  cmd {cmd:02x}: failed {e}")


listen_7060("A) 7060 request only")
handshake_8060()
listen_7060("B) 7060 after 8060 handshake")

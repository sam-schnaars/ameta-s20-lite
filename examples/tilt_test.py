"""Probe camera tilt over Wi-Fi via the app's richer 0x68 control packet (PTZ_V field). Motors stay OFF.

    .venv/bin/python examples/tilt_test.py

Sends the normal neutral 0x66 heartbeat the whole time (flags 0 -> no takeoff/unlock), plus the app's
neutral `68 01 0d ...` packet with ONLY the 2-bit PTZ_V field changed:
    LightOn=1, PTZ_V=1/2/3, PTZ_H=1/2 -- 3 s each, 2 s idle between (about 36 s total)
and measures vertical image shift from the live video (phase correlation) during each phase.
"""
import os, socket, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cv2, numpy as np
import protocol as P
import video

ADDR = (P.DRONE_IP, P.DRONE_PORT)
# app's neutral 0x68/01 payload from capture 06: sticks 0x80, trims 0x20 (centre), CtrlPanel=1
BASE = bytearray.fromhex("8080808020080000010000000000")[:13]


# bit offsets in the 0x68/01 bitfield (from the app's debug print): PTZ_H 60-61, PTZ_V 62-63, LightOn 66
FIELDS = {"PTZ_H": (60, 2), "PTZ_V": (62, 2), "LightOn": (66, 1)}


def ctrl68(ptz_v=0, **fields):
    pl = bytearray(BASE)
    bits = int.from_bytes(pl[:9], "little")
    fields.setdefault("PTZ_V", ptz_v)
    for name, val in fields.items():
        off, width = FIELDS[name]
        mask = ((1 << width) - 1) << off
        bits = (bits & ~mask) | ((val << off) & mask)
    pl[:9] = bits.to_bytes(9, "little")
    body = bytes([0x01, len(pl)]) + bytes(pl)
    x = 0
    for b in body:
        x ^= b
    return bytes([0x68]) + body + bytes([x])


assert ctrl68(0).hex() == "68010d8080808020080000010000000025", ctrl68(0).hex()

OUT = os.path.join(os.path.dirname(__file__), "..", "captures", "tilt")
os.makedirs(OUT, exist_ok=True)
log_lines = []


def log(msg):
    print(msg, flush=True)
    log_lines.append(msg)


log("waiting for the drone (join the Mac to the drone's Wi-Fi)...")
while True:
    try:
        socket.create_connection((P.DRONE_IP, video.VIDEO_PORT), timeout=1).close()
        break
    except OSError:
        time.sleep(1)
log("drone reachable -- starting in 2 s. WATCH THE CAMERA.")
time.sleep(2)

sock = P.open_socket()
ptz = {"v": {}}
stop = threading.Event()


def sender():
    n = 0
    while not stop.is_set():
        sock.sendto(P.NEUTRAL, ADDR)                       # heartbeat, flags 0
        if n % 2 == 0:
            sock.sendto(ctrl68(**ptz["v"]), ADDR)         # ~22 Hz
        n += 1
        time.sleep(1 / P.SEND_HZ)


# video: track vertical shift between consecutive frames
shift = {"dy": 0.0}
frame = {"img": None}
prev = {"g": None}


def watcher(stream):
    dec = video.Decoder()
    for chunk in stream:
        for img in dec.frames(chunk):
            frame["img"] = img
            g = cv2.cvtColor(cv2.resize(img, (320, 180)), cv2.COLOR_BGR2GRAY).astype(np.float32)
            if prev["g"] is not None:
                (dx, dy), _ = cv2.phaseCorrelate(prev["g"], g)
                shift["dy"] += dy * 4                      # back to 720p pixels
            prev["g"] = g
        if stop.is_set():
            return


stream = video.LiveStream()
threading.Thread(target=watcher, args=(stream,), daemon=True).start()
threading.Thread(target=sender, daemon=True).start()
time.sleep(1.5)

results = []
try:
    PHASES = [("idle", {}, 2), ("LightOn=1", {"LightOn": 1}, 3), ("idle", {}, 2),
              ("PTZ_V=1", {"PTZ_V": 1}, 3), ("idle", {}, 2), ("PTZ_V=2", {"PTZ_V": 2}, 3), ("idle", {}, 2),
              ("PTZ_V=3", {"PTZ_V": 3}, 3), ("idle", {}, 2),
              ("PTZ_H=1", {"PTZ_H": 1}, 3), ("idle", {}, 2), ("PTZ_H=2", {"PTZ_H": 2}, 3), ("idle", {}, 2)]
    t_start = time.time()
    for label, v, secs in PHASES:
        ptz["v"] = v
        start = shift["dy"]
        log(f"t={time.time() - t_start:5.1f}s  {label:10} sending {ctrl68(**v).hex()} for {secs} s")
        if frame["img"] is not None:
            cv2.imwrite(os.path.join(OUT, f"{len(results)}_{label.replace('=', '')}_start.jpg"), frame["img"])
        time.sleep(secs)
        if frame["img"] is not None:
            cv2.imwrite(os.path.join(OUT, f"{len(results)}_{label.replace('=', '')}_end.jpg"), frame["img"])
        results.append((label, shift["dy"] - start))
finally:
    ptz["v"] = {}
    time.sleep(0.3)
    stop.set()
    stream.close()

log("\nvertical image shift per phase (pixels, + = image content moved DOWN = camera tilted UP):")
for label, dy in results:
    log(f"  {label:8} {dy:+7.1f}")
log("video frames seen: " + ("yes" if frame["img"] is not None else "NO (video failed)"))
open(os.path.join(OUT, "result.txt"), "w").write("\n".join(log_lines) + "\n")
print(f"\nsaved {OUT}/result.txt and snapshots -- rejoin your normal Wi-Fi and tell Claude.")

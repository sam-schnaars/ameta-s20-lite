"""Interactive servo bench for designing the grab/release mechanism. No flying, no drone needed.

    .venv/bin/python examples/servo_bench.py           # via the ground station (radio), or
    .venv/bin/python examples/servo_bench.py --usb     # harness plugged straight into USB

Type a command and press Enter:
    45          go to 45 degrees            +5 / -5     nudge from current angle (any number)
    hold        go to the saved HOLD angle  rel         go to the saved RELEASE angle
    sethold     save CURRENT angle as HOLD  setrel      save CURRENT angle as RELEASE   (kept after power-off)
    cycle       real drop: ARM -> RELEASE -> wait 2 s -> CLOSE
    sweep       slowly 0 -> 180 -> 0 in 15-degree steps (see the full range of motion)
    angles      show saved hold/release and current angle
    q           quit (latch is left where it is)
"""
import argparse, glob, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import serial
from harness import Harness


class UsbHarness:
    """Talk to the harness directly over its own USB serial (bench only)."""

    def __init__(self):
        for p in sorted(glob.glob("/dev/cu.usbmodem*")):
            s = serial.Serial(p, 115200, timeout=0.3)
            time.sleep(0.6); s.reset_input_buffer(); s.write(b"WHO\n"); time.sleep(0.5)
            if b"HARNESS" in s.read(400):
                self.s = s
                print(f"harness on USB {p}")
                return
            s.close()
        sys.exit("no harness found on USB")

    def send(self, cmd):
        self.s.reset_input_buffer()
        self.s.write((cmd + "\n").encode())
        end = time.time() + 2
        buf = b""
        while time.time() < end:
            buf += self.s.read(200)
            for line in buf.decode(errors="replace").splitlines():
                line = line.strip()
                if line and not line.startswith(("radio ", "arm expired")):
                    return line
        raise RuntimeError(f"no answer to {cmd!r}")


ap = argparse.ArgumentParser()
ap.add_argument("--usb", action="store_true", help="harness plugged into this Mac's USB instead of radio")
args = ap.parse_args()
h = UsbHarness() if args.usb else Harness.discover(timeout=15)


def current():
    r = h.send("ANGLES").split()          # ANGLES hold <h> release <r> now <c>
    return int(r[2]), int(r[4]), int(r[6])


print(__doc__.split("Type a command")[1].split('"""')[0])
print(h.send("ANGLES"))
while True:
    try:
        c = input("servo> ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print(); break
    try:
        if c in ("q", "quit", "exit"):
            break
        elif c.lstrip("+-").isdigit() and c[0] in "+-":
            print(h.send(f"ANGLE {max(0, min(180, current()[2] + int(c)))}"))
        elif c.isdigit():
            print(h.send(f"ANGLE {c}"))
        elif c == "hold":
            print(h.send("CLOSE"))
        elif c in ("rel", "release"):
            hold, rel, _ = current()
            print(h.send(f"ANGLE {rel}"), "(moved only -- use 'cycle' for a real armed drop)")
        elif c == "sethold":
            print(h.send(f"SETHOLD {current()[2]}"))
        elif c == "setrel":
            print(h.send(f"SETRELEASE {current()[2]}"))
        elif c == "cycle":
            print(h.send("CLOSE")); time.sleep(0.8)
            print(h.send("ARM")); print(h.send("RELEASE"), " <- drop"); time.sleep(2)
            print(h.send("CLOSE"))
        elif c == "sweep":
            for a in list(range(0, 181, 15)) + list(range(165, -1, -15)):
                print(h.send(f"ANGLE {a}"), end="\r", flush=True); time.sleep(0.35)
            print()
        elif c == "angles":
            print(h.send("ANGLES"))
        elif c:
            print("?  try: 45  +5  -5  hold  rel  sethold  setrel  cycle  sweep  angles  q")
    except RuntimeError as e:
        print("!!", e)

"""Calibrate one axis with a short real flight, then save the result into the code.

    python3 calibrate.py pitch     # finds which byte direction is FORWARD + metres/second
    python3 calibrate.py roll      # metres/second sideways (direction already known: right)
    python3 calibrate.py up        # metres/second climbing
    python3 calibrate.py yaw       # degrees/second rotating
    options: --seconds 1.0  (push length)   Ctrl-C at any time = land

Flight: takeoff -> settle -> ONE push at calibration.REF_SPEED -> hover -> land.
Then it asks what you saw and writes protocol.py / calibration.py.
"""
import argparse, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import calibration as C
import protocol as P
from drone import S20Lite

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("axis", choices=["pitch", "roll", "up", "yaw"])
ap.add_argument("--seconds", type=float, default=1.0)
a = ap.parse_args()
secs = a.seconds
if not 0.3 <= secs <= 3:
    sys.exit("--seconds must be between 0.3 and 3")


def set_const(fname, name, value):
    path = os.path.join(HERE, fname)
    s = open(path).read()
    new, n = re.subn(rf"^{name} = [^\n#]*?(\s*#|$)", rf"{name} = {value!r}\1", s, count=1, flags=re.M)
    if n != 1:
        sys.exit(f"could not find {name} in {fname}")
    open(path, "w").write(new)
    print(f"  saved {fname}: {name} = {value!r}")


def ask_float(q):
    while True:
        r = input(q).strip()
        if r == "":
            return None
        try:
            return float(r)
        except ValueError:
            print("  type a number, or just Enter to skip")


desc = {
    "pitch": "pitch byte ABOVE 0x80 (forward OR backward -- that's what we're finding out). "
             "Keep 3 m clear IN FRONT AND BEHIND the drone",
    "roll": "slide RIGHT. Keep 3 m clear to the drone's right",
    "up": "climb. Keep the area above clear (no ceiling under 3 m)",
    "yaw": "rotate RIGHT in place",
}[a.axis]
print(f"Calibrating {a.axis}: takeoff, then {desc}, at speed {C.REF_SPEED} for {secs:.1f} s, then land.")
print("Before takeoff: note the drone's position/heading (a marker on the ground helps).")
if input("Open area, nobody within 10 m, app closed everywhere? type 'yes': ").strip().lower() != "yes":
    sys.exit("aborted")

with S20Lite() as d:
    d.takeoff()
    if a.axis == "pitch":
        d._move("pitch", P.stick_value(C.REF_SPEED), secs)      # raw direction, sign unknown on purpose
    elif a.axis == "roll":
        d.right(speed=C.REF_SPEED, duration=secs)
    elif a.axis == "up":
        d.up(speed=C.REF_SPEED, duration=secs)
    else:
        d.rotate_right(speed=C.REF_SPEED, duration=secs)
    d.hover(2)
    d.land()

print("\n--- what did you see? ---")
if a.axis == "pitch":
    r = ""
    while r not in ("f", "b", "n"):
        r = input("Did it move (f)orward (nose direction), (b)ackward, or (n)ot noticeably? ").strip().lower()
    if r == "n":
        sys.exit("no movement: rerun with --seconds 2")
    set_const("protocol.py", "PITCH_FORWARD_SIGN", +1 if r == "f" else -1)
    m = ask_float("How far did it move, in metres? (Enter to skip) ")
    if m:
        set_const("calibration.py", "PITCH_M_PER_S", round(m / secs, 3))
elif a.axis in ("roll", "up"):
    m = ask_float(f"How far did it {'slide right' if a.axis == 'roll' else 'climb'}, in metres? ")
    if m:
        set_const("calibration.py", "ROLL_M_PER_S" if a.axis == "roll" else "THROTTLE_M_PER_S", round(m / secs, 3))
else:
    deg = ask_float("How many degrees did it rotate? ")
    if deg:
        set_const("calibration.py", "YAW_DEG_PER_S", round(deg / secs, 1))
print("done.")

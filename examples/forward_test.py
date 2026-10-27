"""Forward drop flight: takeoff -> climb 1 s -> forward 0.5 s -> hover 1 s -> RELEASE -> back 1 s -> land.

    cd ~/Gabriel/ameta_s20 && .venv/bin/python examples/forward_test.py
    options: --up 1.0 --forward 0.5 --hover 1.0 --back 1.0 --speed 0.2

Needs: `python3 calibrate.py pitch` done once (so the code knows which way is forward), harness ON and
mounted (latch closed), ground XIAO on the Mac's USB, Mac on the drone's Wi-Fi, AMETA app closed.
Ctrl-C at any time = land (no release). Harness and pitch calibration are checked BEFORE takeoff.
"""
import argparse, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import protocol as P
from drone import S20Lite
from harness import prepare_for_flight, safe_release

ap = argparse.ArgumentParser()
ap.add_argument("--up", type=float, default=1.0, help="climb seconds after takeoff (max 3)")
ap.add_argument("--forward", type=float, default=0.5, help="forward seconds (max 3)")
ap.add_argument("--hover", type=float, default=1.0, help="hover seconds before the drop")
ap.add_argument("--back", type=float, default=1.0, help="backward seconds after the drop (max 3)")
ap.add_argument("--speed", type=float, default=0.2, help="stick for climb/forward/back (max 0.3)")
a = ap.parse_args()
clip = lambda v: max(0.0, min(v, 3.0))
up, fwd, hov, back = clip(a.up), clip(a.forward), clip(a.hover), clip(a.back)
speed = max(0.05, min(abs(a.speed), 0.3))

if P.PITCH_FORWARD_SIGN is None:
    sys.exit("not flying: forward/back direction isn't calibrated yet.\n"
             "Run once (props on, open area, keep 3 m clear front AND back):  python3 calibrate.py pitch")

try:
    harness = prepare_for_flight()
except RuntimeError as e:
    sys.exit(f"not flying: {e}")

print(f"\nPlan: takeoff (~1.2 m) -> up {up:.1f} s -> forward {fwd:.1f} s -> hover {hov:.1f} s -> RELEASE "
      f"-> back {back:.1f} s -> land   (speed {speed:.0%})")
print("Checklist: open area, nobody within 10 m, 3 m clear in front, nothing under the drop point.")
if input("Type 'yes' to fly: ").strip().lower() != "yes":
    harness.close_link()
    sys.exit("aborted")

try:
    with S20Lite() as d:
        d.takeoff()
        if up:
            d.up(speed=speed, duration=up)
        if fwd:
            d.forward(speed=speed, duration=fwd)
        d.hover(hov)
        if not harness.link_ok():
            print("RELEASE SKIPPED: no harness heartbeat (out of radio range?)")
        else:
            ok, msg = safe_release(harness)
            print(("RELEASE: " if ok else "RELEASE FAILED: ") + msg)
        if back:
            d.back(speed=speed, duration=back)
        d.hover(1.0)
        d.land()
finally:
    try:
        harness.close()
    except RuntimeError:
        pass
    harness.close_link()

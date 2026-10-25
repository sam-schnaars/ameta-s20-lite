"""First drop flight: takeoff (~1.2 m) -> climb 0.5 s -> hover -> RELEASE -> hover -> land.

    cd ~/Gabriel/ameta_s20 && .venv/bin/python examples/drop_test.py            # climb 0.5 s
    .venv/bin/python examples/drop_test.py --up 1.0                            # gentler climb

Needs: harness ON and mounted (latch closed), ground XIAO on the Mac's USB, Mac on the drone's Wi-Fi,
AMETA app closed everywhere. No internet needed. Ctrl-C at any time = land (no release).
The harness is checked BEFORE takeoff; if it doesn't answer, the drone doesn't fly.
"""
import argparse, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from drone import S20Lite
from harness import prepare_for_flight, safe_release

ap = argparse.ArgumentParser()
ap.add_argument("--up", type=float, default=0.5, help="seconds of climb at --speed after takeoff (max 3)")
ap.add_argument("--speed", type=float, default=0.2, help="throttle stick for the climb (max 0.3)")
args = ap.parse_args()
up = max(0.0, min(args.up, 3.0))
speed = max(0.05, min(abs(args.speed), 0.3))

try:
    harness = prepare_for_flight()          # finds harness via ground station, closes latch
except RuntimeError as e:
    sys.exit(f"not flying: {e}")

print(f"\nPlan: takeoff (~1.2 m) -> climb {up:.1f} s at {speed:.0%} -> hover 2 s -> RELEASE -> hover 2 s -> land")
print("Checklist: open area, nobody within 10 m, nothing under the drone, app closed everywhere.")
if input("Type 'yes' to fly: ").strip().lower() != "yes":
    harness.close_link()
    sys.exit("aborted")

try:
    with S20Lite() as d:
        d.takeoff()
        if up > 0:
            d.up(speed=speed, duration=up)
        d.hover(2)
        if not harness.link_ok():
            print("RELEASE SKIPPED: no harness heartbeat (out of radio range?)")
        else:
            ok, msg = safe_release(harness)
            print(("RELEASE: " if ok else "RELEASE FAILED: ") + msg)
        d.hover(2)
        d.land()
finally:
    try:
        harness.close()                     # latch back to hold after landing
    except RuntimeError:
        pass
    harness.close_link()

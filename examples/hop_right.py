"""Takeoff (~1.2 m = ~4 ft), move right ~3 ft, land.  PROPS ON -> open area, nobody near.

usage: python3 examples/hop_right.py [speed] [seconds]     defaults 0.2 for 1.0 s
Calibrate: run once with defaults, measure how far it moved, then scale seconds to hit ~3 ft (0.9 m).
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import protocol as P
from drone import S20Lite

speed = float(sys.argv[1]) if len(sys.argv) > 1 else 0.2
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0

if P.ROLL_AXIS is None:
    sys.exit("roll axis not decoded yet: capture 06_roll_right first")
print(f"Plan: takeoff -> settle -> right at {speed:.2f} (byte 0x{P.stick_value(speed * P.ROLL_RIGHT_SIGN):02x}) "
      f"for {secs:.2f} s -> hover 2 s -> land.  Ctrl-C = land.")
if input("Open area, nobody within 10 m, app closed everywhere? type 'yes': ").strip().lower() != "yes":
    sys.exit("aborted")

with S20Lite() as drone:
    drone.takeoff()
    drone.right(speed=speed, duration=secs)
    drone.hover(2)
    drone.land()

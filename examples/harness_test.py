"""Radio test for the payload harness (no flying): laptop -> ground XIAO (USB) -> ESP-NOW -> harness.

    .venv/bin/python examples/harness_test.py   # find harness, PING, ARM, RELEASE, CLOSE, check the arm timeout

Ground XIAO plugged into the Mac (firmware/ground); harness on its battery, switched on.
"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from harness import Harness

print("looking for the ground station and the harness heartbeat (switch the harness ON)...")
h = Harness.discover(timeout=30)

print("signal:", h.last_hello[1], "dBm (closer to 0 = stronger; below about -90 is unreliable)")
t = time.time(); print("PING   ->", h.ping(), f"({(time.time() - t) * 1000:.0f} ms)")
print("CLOSE  ->", h.close())
time.sleep(1)
r = h.send("RELEASE"); print("RELEASE without ARM ->", r, "(should be REFUSED)")
h.arm(); print("ARM    -> ARMED")
print("RELEASE ->", "RELEASED" if h.release() else "?", "   <- servo should turn now")
time.sleep(1.5)
print("CLOSE  ->", h.close(), "   <- servo back to hold")
h.arm(); print("ARM again, waiting 11 s for it to expire...")
time.sleep(11)
print("RELEASE after timeout ->", h.send("RELEASE"), "(should be REFUSED)")
print("PING   ->", h.ping())
print("\nall radio checks done")

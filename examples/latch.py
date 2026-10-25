"""Quick latch control via the ground station.

    .venv/bin/python examples/latch.py open        # release and stay open
    .venv/bin/python examples/latch.py open 5      # release, wait 5 s, close
    .venv/bin/python examples/latch.py close
"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from harness import Harness, safe_release

if len(sys.argv) < 2 or sys.argv[1] not in ("open", "close"):
    sys.exit(__doc__)
h = Harness.discover(timeout=12)
try:
    if sys.argv[1] == "close":
        print("CLOSE:", h.close())
    else:
        ok, msg = safe_release(h)
        print("OPEN:", msg)
        if len(sys.argv) > 2:
            time.sleep(float(sys.argv[2]))
            print("CLOSE:", h.close())
finally:
    h.close_link()

"""Live radio range monitor: walk the harness around and watch the link. Ctrl-C to stop.

    .venv/bin/python examples/range_test.py

Pings ~3x/s (single try, no retries) and prints signal + success rate over the last 20 pings.
Rough guide: success >= 90% and signal > -80 dBm = good to fly at that distance.
"""
import os, sys, time
from collections import deque
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from harness import Harness

h = Harness.discover(timeout=20)
h.retries = 1
recent = deque(maxlen=20)
print("move the harness around; Ctrl-C to stop\n")
try:
    while True:
        try:
            h.ping(); recent.append(1)
        except RuntimeError:
            recent.append(0)
        rate = 100 * sum(recent) / len(recent)
        age = time.time() - h.last_hello[2] if h.last_hello else 99
        sig = h.last_hello[1] if h.last_hello and age < 3 else None
        verdict = "GOOD" if rate >= 90 and sig is not None and sig > -80 else "MARGINAL" if rate >= 60 else "BAD"
        bar = "#" * int(rate / 5)
        print(f"\rsignal {sig if sig is not None else '  --'} dBm   success {rate:5.1f}% {bar:<20} {verdict:8}", end="", flush=True)
        time.sleep(0.3)
except KeyboardInterrupt:
    print()
finally:
    h.close_link()

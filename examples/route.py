"""Fly a route written in plain words. Takeoff is automatic at the start, land at the end.

    python3 examples/route.py "up 0.5m, left 1m, hover 2, land"
    python3 examples/route.py "right 2s, rotate right 1s, down 0.3m" --dry-run

Moves:  forward|back|left|right|up|down <N>m  or  <N>s       (metres need calibration.py, seconds always work)
        rotate left|right <N>deg  or  <N>s
        hover <N>                                (seconds)
        release                                  drop the payload (ESP-NOW harness; checked before takeoff)
        land                                     (optional; always lands at the end)
forward/back need `python3 calibrate.py pitch` first (direction unknown until then).
--dry-run prints the plan without connecting. Ctrl-C at any time = land.
"""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import calibration as C
import protocol as P
from drone import S20Lite
from harness import prepare_for_flight, safe_release

RATE = {"forward": C.PITCH_M_PER_S, "back": C.PITCH_M_PER_S, "left": C.ROLL_M_PER_S, "right": C.ROLL_M_PER_S, "up": C.THROTTLE_M_PER_S,
        "down": C.THROTTLE_M_PER_S, "rotate": C.YAW_DEG_PER_S}
STEP = re.compile(r"^(rotate\s+(?:left|right)|forward|back|left|right|up|down|hover|release|land)\s*([\d.]+)?\s*(m|s|deg)?$")


def parse(route):
    plan, height = [], C.TAKEOFF_HEIGHT_M
    for raw in filter(None, (x.strip().lower() for x in route.split(","))):
        m = STEP.match(raw)
        if not m:
            sys.exit(f"don't understand step: {raw!r}")
        verb, num, unit = m.group(1), m.group(2), m.group(3)
        if verb == "land":
            break
        if verb == "release":
            plan.append(("release", None, 0.0, raw)); continue
        if num is None:
            sys.exit(f"step needs a number: {raw!r}")
        n = float(num)
        if verb == "hover":
            plan.append(("hover", None, n, raw)); continue
        key = "rotate" if verb.startswith("rotate") else verb
        if key in ("forward", "back") and P.PITCH_FORWARD_SIGN is None:
            sys.exit(f"{raw!r}: run `python3 calibrate.py pitch` first (forward direction unknown)")
        if unit == "s":
            secs = n
        else:
            want = "deg" if key == "rotate" else "m"
            if unit not in (None, want):
                sys.exit(f"{raw!r}: use {want} or s")
            if RATE[key] is None:
                sys.exit(f"{raw!r}: {key} not calibrated yet (calibration.py) -- use seconds instead, e.g. '{verb} 1s'")
            secs = n / RATE[key]
        if key in ("up", "down") and C.THROTTLE_M_PER_S:
            height += (1 if key == "up" else -1) * secs * C.THROTTLE_M_PER_S
            if not C.MIN_HEIGHT_M <= height <= C.MAX_HEIGHT_M:
                sys.exit(f"{raw!r}: estimated height {height:.2f} m is outside "
                         f"{C.MIN_HEIGHT_M}-{C.MAX_HEIGHT_M} m (calibration.py)")
        if key in ("up", "down") and not C.THROTTLE_M_PER_S and secs > 1.5:
            sys.exit(f"{raw!r}: uncalibrated up/down limited to 1.5 s for safety")
        if secs > 5:
            sys.exit(f"{raw!r}: {secs:.1f} s is longer than the 5 s per-step limit; split it up")
        plan.append((verb, key, secs, raw))
    return plan


def main():
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    if not args:
        sys.exit(__doc__)
    plan = parse(args[0])
    print(f"Plan (speed {C.REF_SPEED}):  takeoff (~{C.TAKEOFF_HEIGHT_M} m)")
    for verb, key, secs, raw in plan:
        print(f"   {raw:<24} -> " + ("ARM + RELEASE payload" if verb == "release" else
                                     f"{'hover' if verb == 'hover' else verb} for {secs:.2f} s"))
    print("   land")
    if "--dry-run" in sys.argv:
        return
    harness = None
    if any(v == "release" for v, *_ in plan):
        try:
            harness = prepare_for_flight()
        except RuntimeError as e:
            sys.exit(f"not flying: {e}")
    if input("Open area, nobody within 10 m, app closed everywhere? type 'yes': ").strip().lower() != "yes":
        sys.exit("aborted")
    with S20Lite() as d:
        d.takeoff()
        for verb, key, secs, raw in plan:
            if verb == "hover":
                d.hover(secs)
                continue
            if verb == "release":
                d.stop()
                ok, msg = safe_release(harness)
                print(("RELEASE: " if ok else "RELEASE FAILED: ") + msg)
                d.hover(1.0)
                continue
            fn = {"forward": d.forward, "back": d.back, "left": d.left, "right": d.right, "up": d.up, "down": d.down,
                  "rotate left": d.rotate_left, "rotate right": d.rotate_right}[re.sub(r"\s+", " ", verb)]
            fn(speed=C.REF_SPEED, duration=secs)
            d.hover(1.0)          # let it settle between moves
        d.land()


if __name__ == "__main__":
    main()

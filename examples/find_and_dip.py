"""Describe something in plain words; the drone finds it, turns to face it, dips down, comes back up, lands.

    export OPENAI_API_KEY=sk-...        (once per Terminal window)
    .venv/bin/python examples/find_and_dip.py "the yellow cabinet" --no-fly      # table test
    .venv/bin/python examples/find_and_dip.py "the yellow cabinet"               # fly

Steps:  takeoff -> [HEIGHT: --height 0.3 / --height-s 1.0] -> SCAN (rotate slowly until the AI sees the target) -> CENTER (turn until it's in the
middle) -> DIP (throttle down, pause [--release: drop payload here], throttle back up) -> land.
Only rotation and up/down -- never forward/sideways. The AI only reports what it sees; the flying is
done by local loops. Stale or missing AI answers -> hold still. Time limit, Ctrl-C or q -> land.

Every run is logged to captures/missions/<time>_<target>/ (events.jsonl, every AI frame, contact.jpg, summary.txt).

Options: --engine decisions|responses  --model gpt-6-luna  --hz 3  --dip-seconds 1.0  --dip-speed 0.2  --scan-speed 0.15
         --seconds 60  --min-confidence 0.6
"""
import argparse, os, shutil, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cv2
import video
import calibration as C
from ai_vision import make_locator, DEFAULT_MODEL
from mission_log import MissionLog

ap = argparse.ArgumentParser()
ap.add_argument("target", help='what to look for, e.g. "the yellow cabinet"')
ap.add_argument("--no-fly", action="store_true")
ap.add_argument("--engine", choices=["decisions", "responses"], default="decisions",
                help="decisions = OpenAI Decisions API (fast, gpt-6-luna); responses = JSON answer with notes")
ap.add_argument("--model", default=DEFAULT_MODEL, help="responses engine only")
ap.add_argument("--hz", type=float, default=3.0, help="AI calls per second")
ap.add_argument("--seconds", type=float, default=60, help="overall time limit")
ap.add_argument("--scan-speed", type=float, default=0.15, help="yaw stick while searching")
ap.add_argument("--max-yaw", type=float, default=0.25)
ap.add_argument("--gain", type=float, default=0.35)
ap.add_argument("--center-tol", type=float, default=0.15, help="|x| below this counts as centred")
ap.add_argument("--min-confidence", type=float, default=0.6)
ap.add_argument("--dip-seconds", type=float, default=1.0, help="throttle-down time (max 1.5 until 'up' is calibrated)")
ap.add_argument("--dip-speed", type=float, default=0.2, help="throttle stick for the dip (max 0.3)")
ap.add_argument("--settle", type=float, default=3.0)
ap.add_argument("--no-window", action="store_true")
ap.add_argument("--release", action="store_true",
                help="drop the payload (ESP-NOW harness) at the bottom of the dip; harness is checked before takeoff")
ap.add_argument("--vertical", action="store_true",
                help="also climb/descend gently to keep the target vertically centred (height-budgeted)")
ap.add_argument("--v-speed", type=float, default=0.15, help="throttle stick for vertical tracking (max 0.25)")
ap.add_argument("--v-budget", type=float, default=1.5,
                help="uncalibrated floor/ceiling guard: max net seconds (at 20%% throttle) up or down from takeoff height")
ap.add_argument("--height", type=float, default=None,
                help="metres to climb (+) or descend (-) from the ~1.2 m takeoff height before scanning (needs calibrate.py up)")
ap.add_argument("--height-s", type=float, default=None,
                help="same, but in seconds at 20%% throttle (+ up, - down); works without calibration")
args = ap.parse_args()
args.dip_seconds = max(0.2, min(args.dip_seconds, 1.5))
args.dip_speed = min(abs(args.dip_speed), 0.3)
args.max_yaw = min(abs(args.max_yaw), 0.4)
args.v_speed = min(abs(args.v_speed), 0.25)
args.v_budget = min(abs(args.v_budget), 2.0)

# ---- height bookkeeping: everything in "seconds at 20% throttle" (h20) from takeoff height -------
H_REF = 0.2
if C.THROTTLE_M_PER_S:                       # calibrated: limits from calibration.py heights
    m_per_h20 = C.THROTTLE_M_PER_S * H_REF / C.REF_SPEED
    budget_up = (C.MAX_HEIGHT_M - C.TAKEOFF_HEIGHT_M) / m_per_h20
    budget_down = (C.TAKEOFF_HEIGHT_M - C.MIN_HEIGHT_M) / m_per_h20
else:
    m_per_h20 = None
    budget_up = budget_down = args.v_budget
target_h20 = 0.0
if args.height is not None:
    if not m_per_h20:
        sys.exit("--height needs a calibrated climb rate: run `python3 calibrate.py up` (or use --height-s)")
    target_h20 = args.height / m_per_h20
elif args.height_s is not None:
    target_h20 = args.height_s
if not -budget_down <= target_h20 <= budget_up:
    sys.exit(f"requested height is outside the floor/ceiling guard ({-budget_down:.1f}..{budget_up:.1f} s at 20%"
             + (f", {C.MIN_HEIGHT_M}-{C.MAX_HEIGHT_M} m" if m_per_h20 else "") + ")")
h20 = 0.0          # estimated net climb since takeoff, in seconds at 20% throttle (+ = up)


def h_text():
    return f"{h20:+.1f}s" + (f" ({C.TAKEOFF_HEIGHT_M + h20 * m_per_h20:.2f} m)" if m_per_h20 else "")

loc = make_locator(args.target, engine=args.engine, model=args.model)
harness = None
if args.release:
    from harness import prepare_for_flight, safe_release
    try:
        harness = prepare_for_flight()
    except RuntimeError as e:
        sys.exit(f"not flying: {e}")
log = MissionLog(args.target, meta={"args": vars(args), "engine_model": loc.model, "no_fly": args.no_fly})
loc.on_result = log.ai
print(f"logging to {log.dir}")
print(f"Looking for: {args.target!r} via {args.engine} ({loc.model}) at ~{args.hz:g} Hz")

drone = None
if not args.no_fly:
    from drone import S20Lite
    print(f"FLIGHT: takeoff, scan for {args.target!r}, centre on it, dip {args.dip_seconds:.1f} s down/up, land.")
    print("Needs internet AND the drone's Wi-Fi at once (iPhone USB hotspot + Mac Wi-Fi on the drone).")
    if input("Open space, nobody close, app closed everywhere? type 'yes': ").strip().lower() != "yes":
        sys.exit("aborted")

# ---- video in a background thread: always have the newest frame -------------------------
latest = {"img": None, "t": 0.0}
stop = threading.Event()
stream = video.LiveStream()


def video_loop():
    dec = video.Decoder()
    try:
        for chunk in stream:
            for img in dec.frames(chunk):
                latest["img"], latest["t"] = img, time.time()
            if stop.is_set():
                return
    except Exception as e:
        print("video stopped:", e)


def ai_loop():
    period = 1.0 / max(0.5, args.hz)
    while not stop.wait(period):
        if latest["img"] is not None and time.time() - latest["t"] < 0.5:
            loc.submit(latest["img"].copy())


last_cmd = {}


def set_stick(axis, v):
    if last_cmd.get(axis) != v:                      # log only changes
        last_cmd[axis] = v
        log.event("stick", axis=axis, value=round(v, 3), h20=round(h20, 2))
    if drone:
        drone.set_stick(axis, v)


def move_height(delta_h20, speed=H_REF):
    """Climb (+) / descend (-) by delta seconds-at-20%, blocking. Updates h20."""
    global h20
    if abs(delta_h20) < 0.05:
        return
    secs = abs(delta_h20) * H_REF / speed
    set_stick("throttle", speed if delta_h20 > 0 else -speed)
    time.sleep(secs)
    set_stick("throttle", 0.0)
    h20 += delta_h20


# ---- mission state machine ----------------------------------------------------------------
state, state_t, centred_hits, scan_dir, msg = ("HEIGHT" if abs(target_h20) >= 0.05 else "SCAN"), time.time(), 0, 1, ""
last_seen_x = None


def go(s):
    global state, state_t
    state, state_t = s, time.time()
    log.event("state", state=s, h20=round(h20, 2))
    print(f"\n-> {s}")


threading.Thread(target=video_loop, daemon=True).start()
try:
    if not args.no_fly:
        drone = S20Lite()
        drone.connect()
        drone.takeoff(settle=args.settle)
    threading.Thread(target=ai_loop, daemon=True).start()
    t_end = time.time() + args.seconds
    last_result_time = 0.0
    last_status, last_print = "", 0.0
    loop_t = time.time()
    while state != "DONE":
        now = time.time()
        if now > t_end:
            print("\ntime limit"); log.event("stop", reason="time limit"); break
        r = loc.latest(max_age=1.6)          # answers arrive ~1 s after their frame
        seen = r is not None and r.found and r.confidence >= args.min_confidence
        fresh = r is not None and r.frame_time > last_result_time
        if r is not None:
            last_result_time = max(last_result_time, r.frame_time)
        yaw = 0.0

        if state == "HEIGHT":
            set_stick("yaw", 0.0)
            print(f"\nHEIGHT: moving {target_h20:+.1f} s at 20% throttle" +
                  (f" (~{target_h20 * m_per_h20:+.2f} m)" if m_per_h20 else ""))
            move_height(target_h20)
            time.sleep(1.0)
            go("SCAN")
            continue
        elif state == "SCAN":
            if seen:
                go("CENTER"); centred_hits = 0
            elif now - state_t > 40:
                print("\ncould not find it after a full search"); log.event("stop", reason="not found after search"); break
            else:
                yaw = args.scan_speed * scan_dir
        elif state == "CENTER":
            if r is None:                                  # no recent answer -> hold
                yaw = 0.0
            elif not seen:
                if now - state_t > 4:                      # lost it: search again, toward where it was
                    scan_dir = 1 if (last_seen_x or 0) >= 0 else -1
                    go("SCAN")
            else:
                last_seen_x = r.x
                yaw = 0.0 if abs(r.x) < args.center_tol * 0.6 else max(-args.max_yaw, min(args.max_yaw, args.gain * r.x))
                if fresh:
                    at_limit = h20 <= -budget_down if r.y > 0 else h20 >= budget_up
                    ok_v = (not args.vertical) or abs(r.y) < 0.35 or at_limit
                    centred_hits = centred_hits + 1 if (abs(r.x) < args.center_tol and ok_v) else 0
                if centred_hits >= 3:
                    go("DIP")
        elif state == "DIP":
            set_stick("yaw", 0.0)
            set_stick("throttle", 0.0)
            want = args.dip_seconds * args.dip_speed / H_REF          # dip size in h20 units
            room = max(0.0, budget_down + h20)                        # how far we may still descend
            dip_h20 = min(want, room)
            print(f"\nDIP: down {dip_h20:.1f} s-at-20%  (height {h_text()})" + ("  (shortened: near floor guard)" if dip_h20 < want else ""))
            log.event("dip", want_h20=round(want, 2), dip_h20=round(dip_h20, 2), h20_before=round(h20, 2))
            move_height(-dip_h20, args.dip_speed); time.sleep(1.0)
            if harness:
                ok, msg = safe_release(harness)
                print(("RELEASE: " if ok else "RELEASE FAILED: ") + msg)
                log.event("release", ok=ok, message=msg, h20=round(h20, 2))
            time.sleep(0.5)
            print("DIP: back up")
            move_height(+dip_h20, args.dip_speed); time.sleep(1.0)
            go("DONE")
            continue

        thr = 0.0
        if args.vertical and state == "CENTER" and seen and r is not None:
            if r.y > 0.35 and h20 > -budget_down:      # target low in frame -> go down a bit
                thr = -args.v_speed
            elif r.y < -0.35 and h20 < budget_up:      # target high in frame -> go up a bit
                thr = args.v_speed
        if time.time() - latest["t"] > 0.5:               # video stalled -> don't move blind
            yaw = thr = 0.0
        set_stick("yaw", yaw)
        if args.vertical:
            set_stick("throttle", thr)
            h20 += thr / H_REF * (now - loop_t)
        loop_t = now

        status = (f"{state:6} yaw={yaw:+.2f}" + (f" thr={thr:+.2f}" if args.vertical else "") + f" h={h_text()}" + "  " +
                  (f"AI: {'FOUND' if seen else 'no'} x={r.x:+.2f} y={r.y:+.2f} size={r.size:.2f} "
                   f"conf={r.confidence:.2f} {r.latency:.1f}s '{r.note}'" if r else "AI: waiting")
                  + f"  calls={loc.calls} err={loc.errors}")
        if status != last_status and now - last_print > 0.3:      # redraw at most ~3x/s, never wider than the terminal
            width = shutil.get_terminal_size((100, 20)).columns - 1
            print("\r" + status[:width].ljust(width), end="", flush=True)
            last_status, last_print = status, now
        if loc.errors and loc.calls == 0 and loc.errors >= 3:
            print("\nAI calls failing:", loc.last_error); log.event("stop", reason="AI failing", error=loc.last_error); break

        img = latest["img"]
        if args.no_window:
            time.sleep(0.03)
        elif img is not None:
            img = img.copy(); h, w = img.shape[:2]
            if r is not None and r.found:
                cx, cy = int((r.x + 1) / 2 * w), int((r.y + 1) / 2 * h)
                half = int(max(0.05, r.size) * h / 2)
                cv2.rectangle(img, (cx - half, cy - half), (cx + half, cy + half),
                              (0, 255, 0) if seen else (0, 200, 255), 3)
            cv2.line(img, (w // 2, 0), (w // 2, h), (255, 255, 255), 1)
            cv2.putText(img, ("NO-FLY " if args.no_fly else "") + f"{state}  {args.target}", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
            if r is not None:
                cv2.putText(img, r.note, (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            if not getattr(cv2, "_win_ready", False):
                cv2.namedWindow("find_and_dip", cv2.WINDOW_NORMAL)
                cv2.resizeWindow("find_and_dip", 960, 540)
                cv2.setWindowProperty("find_and_dip", cv2.WND_PROP_TOPMOST, 1)
                cv2._win_ready = True
            cv2.imshow("find_and_dip", img)
            if cv2.waitKey(30) & 0xFF == ord("q"):
                raise KeyboardInterrupt
except KeyboardInterrupt:
    print("\nstopping")
finally:
    stop.set()
    if drone:
        drone.stop()
        if drone.state in (0x20, 0x40):
            drone.land()
        drone.close()
    loc.close()
    if harness:
        harness.close_link()
    stream.close()
    cv2.destroyAllWindows()
    time.sleep(0.5)                                  # let in-flight AI answers land in the log
    out = log.close(args.min_confidence)
    print(f"\nmission log: {out}\n" + open(os.path.join(out, "summary.txt")).read())

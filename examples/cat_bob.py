"""Take off, bob gently up/down, and ROTATE to keep the cat centred. Never moves forward/sideways.

    .venv/bin/python examples/cat_bob.py --no-fly        # table test: video + what it WOULD send
    .venv/bin/python examples/cat_bob.py                 # fly: 2 s settle, bob + follow cat for 30 s, land
    options: --seconds 30  --bob-seconds 0.5  --bob-speed 0.2  --no-bob
             --target cat|dog|person  --top 1.0  --max-speed 0.25  --gain 0.4

Bob = throttle up for 0.5 s, then down for 0.5 s, repeated (starts with UP so it never dips first).
Safety: yaw -> 0 if the cat is lost for 0.5 s or video stalls (watchdog); throttle bob stops on exit;
time limit then land; Ctrl-C / q = land.
"""
import argparse, os, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cv2
from ultralytics import YOLO
import video

COCO = {"person": 0, "cat": 15, "dog": 16}

ap = argparse.ArgumentParser()
ap.add_argument("--no-fly", action="store_true")
ap.add_argument("--seconds", type=float, default=30)
ap.add_argument("--settle", type=float, default=2.0, help="hover time after takeoff before starting")
ap.add_argument("--target", choices=COCO, default="cat")
ap.add_argument("--bob-seconds", type=float, default=0.5)
ap.add_argument("--bob-speed", type=float, default=0.2, help="throttle stick for the bob (max 0.3)")
ap.add_argument("--no-bob", action="store_true")
ap.add_argument("--max-speed", type=float, default=0.25)
ap.add_argument("--gain", type=float, default=0.4)
ap.add_argument("--deadband", type=float, default=0.12)
ap.add_argument("--top", type=float, default=1.0,
                help="fraction of frame height searched")
ap.add_argument("--conf", type=float, default=0.35)
args = ap.parse_args()
args.max_speed = min(abs(args.max_speed), 0.5)
args.bob_speed = min(abs(args.bob_speed), 0.3)
args.bob_seconds = max(0.2, min(args.bob_seconds, 1.0))

model = YOLO("yolov8n.pt")
cls = COCO[args.target]
drone = None
if not args.no_fly:
    from drone import S20Lite
    print(f"FLIGHT: takeoff, {args.settle:.0f} s settle, bob +/-{args.bob_seconds} s at {args.bob_speed}, "
          f"rotate to follow the {args.target} for {args.seconds:.0f} s, land.  Ctrl-C / q = land.")
    print(f"Keep the {args.target} at least 2-3 m away; stop immediately if it approaches or jumps.")
    if input("Open space, app closed everywhere? type 'yes': ").strip().lower() != "yes":
        sys.exit("aborted")

stop = threading.Event()
last_update = time.time()


def watchdog():
    while not stop.wait(0.1):
        if time.time() - last_update > 0.5:
            try:
                drone.set_stick("yaw", 0.0)
            except RuntimeError:
                pass


def bob():
    """Throttle up for bob_seconds, down for bob_seconds, repeat. Equal halves -> no net climb."""
    up = True
    while not stop.is_set():
        try:
            drone.set_stick("throttle", args.bob_speed if up else -args.bob_speed)
        except RuntimeError:
            return
        if stop.wait(args.bob_seconds):
            break
        up = not up
    try:
        drone.set_stick("throttle", 0.0)
    except RuntimeError:
        pass


def control(dx):
    if dx is None or abs(dx) < args.deadband:
        return 0.0
    return max(-args.max_speed, min(args.max_speed, args.gain * dx))


stream = video.LiveStream()
dec = video.Decoder()
try:
    if drone is None and not args.no_fly:
        drone = S20Lite()
        drone.connect()
        drone.takeoff(settle=args.settle)
        threading.Thread(target=watchdog, daemon=True).start()
        if not args.no_bob:
            threading.Thread(target=bob, daemon=True).start()
    t_end = time.time() + args.seconds
    last_seen = 0.0
    for chunk in stream:
        for img in dec.frames(chunk):
            now = time.time()
            if now > t_end:
                raise KeyboardInterrupt
            h, w = img.shape[:2]
            area = img[: int(h * args.top)]
            r = model(area, classes=[cls], conf=args.conf, verbose=False)[0]
            dx = None
            if len(r.boxes):
                i = int(r.boxes.conf.argmax())
                x1, y1, x2, y2 = r.boxes.xyxy[i].tolist()
                dx = ((x1 + x2) / 2 - w / 2) / (w / 2)
                last_seen = now
                cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 3)
                cv2.putText(img, f"{args.target} {float(r.boxes.conf[i]):.2f}", (int(x1), max(30, int(y1) - 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
            if now - last_seen > 0.5:
                dx = None
            yaw_cmd = control(dx)
            if drone:
                drone.set_stick("yaw", yaw_cmd)
            last_update = now
            label = f"no {args.target} -> hold" if dx is None else f"dx={dx:+.2f}  yaw={yaw_cmd:+.2f}"
            if args.no_fly:
                print(("[no-fly] " + label).ljust(40), end="\r", flush=True)
            cv2.line(img, (w // 2, 0), (w // 2, h), (255, 255, 255), 1)
            if args.top < 1:
                cv2.line(img, (0, int(h * args.top)), (w, int(h * args.top)), (0, 0, 255), 2)
            cv2.putText(img, ("NO-FLY  " if args.no_fly else "") + label, (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
            cv2.imshow("cat_bob", img)
            if cv2.waitKey(1) & 0xFF == ord("q"):
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
    stream.close()
    cv2.destroyAllWindows()

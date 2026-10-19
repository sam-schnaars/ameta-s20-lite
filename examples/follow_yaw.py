"""Hover in place and ROTATE to keep a person centred in the camera. Never moves forward/sideways.

    .venv/bin/python examples/follow_yaw.py --no-fly        # table test: video + what it WOULD send
    .venv/bin/python examples/follow_yaw.py                 # takeoff, follow by rotating for 60 s, land
    options: --seconds 60  --max-speed 0.25  --gain 0.4  --no-window

Safety: yaw goes to zero if no person is seen for 0.5 s or video stalls for 0.5 s (watchdog);
time limit then land; Ctrl-C or q = land.
"""
import argparse, os, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cv2
from ultralytics import YOLO
import video

ap = argparse.ArgumentParser()
ap.add_argument("--no-fly", action="store_true", help="don't connect to flight controls")
ap.add_argument("--seconds", type=float, default=60)
ap.add_argument("--max-speed", type=float, default=0.25, help="max yaw stick (0..0.5)")
ap.add_argument("--gain", type=float, default=0.4, help="yaw stick per unit of offset")
ap.add_argument("--deadband", type=float, default=0.12, help="ignore offsets smaller than this")
ap.add_argument("--top", type=float, default=1.0, help="fraction of frame height used")
ap.add_argument("--no-window", action="store_true")
args = ap.parse_args()
args.max_speed = min(abs(args.max_speed), 0.5)

model = YOLO("yolov8n.pt")
drone = None
if not args.no_fly:
    from drone import S20Lite
    print(f"FLIGHT MODE: takeoff, rotate to follow for {args.seconds:.0f} s, land. Ctrl-C / q = land.")
    if input("Open space around the drone, app closed everywhere? type 'yes': ").strip().lower() != "yes":
        sys.exit("aborted")

last_update = time.time()
yaw_cmd = 0.0
stop = threading.Event()


def watchdog():
    """If the main loop stops updating (video stall, slow detection), stop rotating."""
    while not stop.wait(0.1):
        if drone and time.time() - last_update > 0.5 and drone.state is not None:
            try:
                drone.set_stick("yaw", 0.0)
            except RuntimeError:
                pass


def control(dx):
    if dx is None or abs(dx) < args.deadband:
        return 0.0
    v = args.gain * dx
    return max(-args.max_speed, min(args.max_speed, v))


stream = video.LiveStream()
dec = video.Decoder()
try:
    if not args.no_fly:
        drone = S20Lite()
        drone.connect()
        drone.takeoff()
        threading.Thread(target=watchdog, daemon=True).start()
    t_end = time.time() + args.seconds
    last_seen = 0.0
    for chunk in stream:
        for img in dec.frames(chunk):
            now = time.time()
            if now > t_end:
                raise KeyboardInterrupt
            h, w = img.shape[:2]
            top = img[: int(h * args.top)]
            r = model(top, classes=[0], conf=0.4, verbose=False)[0]
            dx = None
            if len(r.boxes):
                i = int(r.boxes.conf.argmax())                     # most confident person
                x1, y1, x2, y2 = r.boxes.xyxy[i].tolist()
                dx = ((x1 + x2) / 2 - w / 2) / (w / 2)
                last_seen = now
                cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 3)
            if now - last_seen > 0.5:
                dx = None
            yaw_cmd = control(dx)
            if drone:
                drone.set_stick("yaw", yaw_cmd)
            last_update = now
            label = "no person -> hold" if dx is None else f"dx={dx:+.2f}  yaw={yaw_cmd:+.2f}"
            if args.no_fly:
                print(("[no-fly] " + label).ljust(40), end="\r", flush=True)
            if not args.no_window:
                cv2.line(img, (w // 2, 0), (w // 2, h), (255, 255, 255), 1)
                cv2.line(img, (0, int(h * args.top)), (w, int(h * args.top)), (0, 0, 255), 2)
                cv2.putText(img, ("NO-FLY  " if args.no_fly else "") + label, (20, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
                if not getattr(cv2, "_win_ready", False):
                    cv2.namedWindow("follow_yaw", cv2.WINDOW_NORMAL)
                    cv2.resizeWindow("follow_yaw", 960, 540)
                    cv2.setWindowProperty("follow_yaw", cv2.WND_PROP_TOPMOST, 1)   # keep above Terminal
                    cv2._win_ready = True
                cv2.imshow("follow_yaw", img)
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

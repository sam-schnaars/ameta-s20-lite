"""Live drone camera with person boxes. Read-only: sends NO flight commands.

    .venv/bin/python examples/watch.py                     # live from the drone
    .venv/bin/python examples/watch.py --record clip       # also save captures/clip.mp4
    .venv/bin/python examples/watch.py --no-detect         # video only (faster)
    .venv/bin/python examples/watch.py --file stream.bin   # replay a saved TCP stream

Press q in the window to quit. For each person the overlay shows:
    dx   = horizontal offset from image centre (-1 left .. +1 right)  -> future yaw command
    size = box height / image height                                   -> future approach / stop rule
"""
import argparse, os, shutil, subprocess, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cv2
import video

ap = argparse.ArgumentParser()
ap.add_argument("--record", metavar="NAME", help="save captures/NAME.mp4 (no re-encoding)")
ap.add_argument("--no-detect", action="store_true")
ap.add_argument("--file", help="replay a saved drone->client TCP byte stream")
ap.add_argument("--conf", type=float, default=0.4, help="person detection confidence")
ap.add_argument("--headless", action="store_true", help="no window; print detections")
args = ap.parse_args()

model = None
if not args.no_detect:
    from ultralytics import YOLO
    model = YOLO("yolov8n.pt")        # downloads ~6 MB the first time (needs internet once)

cap_dir = os.path.join(os.path.dirname(__file__), "..", "captures")
raw = open(os.path.join(cap_dir, args.record + ".h264"), "wb") if args.record else None

stream = None
if args.file:
    chunks = video.file_chunks(args.file)
else:
    stream = video.LiveStream()
    chunks = iter(stream)

dec = video.Decoder()
n, t0, fps = 0, time.time(), 0.0
try:
    for chunk in chunks:
        if raw:
            raw.write(chunk)
        for img in dec.frames(chunk):
            n += 1
            if n % 15 == 0:
                fps = 15 / max(1e-6, time.time() - t0)
                t0 = time.time()
            h, w = img.shape[:2]
            people = []
            if model is not None:
                r = model(img, classes=[0], conf=args.conf, verbose=False)[0]
                for (x1, y1, x2, y2), c in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist()):
                    dx = ((x1 + x2) / 2 - w / 2) / (w / 2)
                    size = (y2 - y1) / h
                    people.append((dx, size, c))
                    cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 3)
                    cv2.putText(img, f"person {c:.2f}  dx={dx:+.2f}  size={size:.2f}",
                                (int(x1), max(30, int(y1) - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
            cv2.line(img, (w // 2, 0), (w // 2, h), (255, 255, 255), 1)
            cv2.putText(img, f"{fps:4.1f} fps  people={len(people)}" + ("  REC" if raw else ""),
                        (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
            if args.headless:
                if n % 15 == 0:
                    print(f"frame {n}  {fps:4.1f} fps  people={[(round(d, 2), round(s, 2)) for d, s, _ in people]}")
                continue
            if not getattr(cv2, "_win_ready", False):
                cv2.namedWindow("AMETA S20 Lite", cv2.WINDOW_NORMAL)
                cv2.resizeWindow("AMETA S20 Lite", 960, 540)
                cv2.setWindowProperty("AMETA S20 Lite", cv2.WND_PROP_TOPMOST, 1)   # keep above Terminal
                cv2._win_ready = True
            cv2.imshow("AMETA S20 Lite", img)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                raise KeyboardInterrupt
except KeyboardInterrupt:
    pass
finally:
    if stream:
        stream.close()
    cv2.destroyAllWindows()
    if raw:
        raw.close()
        src = raw.name
        mp4 = src[:-5] + ".mp4"
        if shutil.which("ffmpeg"):
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "h264", "-r", "25", "-i", src,
                            "-c", "copy", mp4])
            print("saved", mp4)
        else:
            print("saved raw", src, "(install ffmpeg to get .mp4)")
    print(f"{n} frames")

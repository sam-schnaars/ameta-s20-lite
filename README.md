# AMETA S20 Lite: Python control, AI vision, and a payload drop

Reverse-engineered Wi-Fi control of the **AMETA S20 Lite** drone (Lewei-family protocol). It's programmable from Python, with the stock flight controller still doing all the stabilization.

- **Flight control:** takeoff, land, and roll/pitch/throttle/yaw over UDP, plus plain-text routes (`"up 0.5m, right 1m, land"`).
- **Live video:** H.264 over TCP, including the fix for the drone's deliberately scrambled mid-frame bytes.
- **Vision:** YOLO person and cat following (rotation only), and **OpenAI-powered "find the yellow cabinet"** missions.
- **Payload harness:** an ESP32-C3 plus a 3.7 g servo, controlled over ESP-NOW, and a **3D-printable pin-pull release**.

`notes.md` is the full lab notebook: every packet, capture and dead end.

> ⚠️ **Safety:** test with the props off first, fly in open space away from people, never drop payloads over people, animals or roads, and follow local drone rules. This is hobby code with no warranty, and the drone has no position feedback, so all moves are timed estimates.

## Protocol summary
| Channel | Details |
|---|---|
| Control | UDP `192.168.0.1:50000` from local port 5010, ~45 Hz: `66 roll pitch throttle yaw flags 00 xor 99` (sticks 0x80 = center; flag 01 = takeoff, 02 = land; xor of bytes 1 to 6) |
| Telemetry | UDP reply, 11 bytes `cc 03 … 33`; byte 3 = state (00 ground, 20 taking off, 40 flying) |
| Video | TCP `:7060`, 46-byte `lewei_cmd` headers; send cmd `01` (keepalive, 1/s) and `02` (start); H.264 with 3 bytes at the middle of each frame restored from header keys (see `video.unscramble`) |
| Camera tilt | Remote-control radio only; not reachable over Wi-Fi |

## Layout
```
protocol.py  drone.py      packet format + S20Lite class (background 45 Hz sender, auto-land on errors)
video.py     video_tables.py   live H.264 stream + unscramble
calibration.py calibrate.py    measured rates; one-push calibration flights
ai_vision.py mission_log.py    OpenAI Decisions/Responses locator; per-run logs + contact sheets
harness.py   firmware/         ESP32 harness + ground station (ESP-NOW)
cad/         pin_release.py → STL (parametric pin-pull release)
examples/    takeoff_land, route, follow_yaw, cat_bob, find_and_dip, watch, servo_bench, harness_test, …
captures/    iphone_cap.py (capture an iPhone's traffic over USB), cap.sh
```

## Quick start
```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
# join the Mac to the drone's Wi-Fi, close the AMETA app everywhere, PROPS OFF:
.venv/bin/python examples/takeoff_land.py
.venv/bin/python examples/watch.py                   # live camera with person boxes
.venv/bin/python examples/route.py "right 1s" --dry-run
```
For AI missions, you need internet and the drone's Wi-Fi at the same time (for example a phone's USB hotspot) and `OPENAI_API_KEY`:
```bash
.venv/bin/python examples/find_and_dip.py "the yellow cabinet" --no-fly
```

## Gotchas we hit
- **macOS 26:** once a process uses system proxy lookup or Apple's TLS trust store (the OpenAI SDK's defaults), it loses access to local-network devices. `ai_vision.make_client()` avoids both.
- **The drone's Wi-Fi is 5 GHz only**, so the ESP32-C3 (2.4 GHz) can't join it, and the harness uses ESP-NOW through a second XIAO on USB.
- XIAO ESP32-C3 boards need their **U.FL antenna**: without it, the signal is about -90 dBm even side by side.

# AMETA S20 Lite protocol notes

Drone AP: `AMETA S20 Lite-BD8FC9`, drone IP `192.168.0.1`, DHCP gives client 192.168.0.x.
Vendor family: **Lewei** (TCP service strings start with ASCII `lewei_cmd`). Source: captures 01_idle, 02_takeoff.

## Channels seen
| channel | dst | notes |
|---|---|---|
| UDP control | 192.168.0.1:50000 (src port 5010) | 17-byte datagrams = 8-byte header + 9-byte control frame, ~46/s (~22 ms) |
| UDP telemetry | 192.168.0.1:50000 -> client:5010 | 19-byte datagrams, ~24/s |
| TCP cmd | 192.168.0.1:8060 | short `lewei_cmd` request/response at connect (2 conns) |
| TCP 7060 | 192.168.0.1:7060 | ~6 MB/24 s drone->app = video stream; also `lewei_cmd` framed requests |

NOTE: UDP "udp.length" 17 = 8 UDP header + 9 payload bytes. tshark's `data.data` shows the 9-byte payload.

## Control frame (UDP, client -> drone)  [idle observed]
command: neutral / heartbeat
packet:  66 80 80 80 80 00 20 20 99
destination: 192.168.0.1:50000
send rate: repeated ~46 Hz (every ~22-24 ms)
observed behavior: drone idle, app showed connected

Layout (hypothesis, to be confirmed with stick captures):
| byte | value | meaning |
|---|---|---|
| 0 | 66 | start |
| 1-4 | 80 80 80 80 | four axes, 0x80 = center (order roll/pitch/throttle/yaw TBD) |
| 5 | 00 | flags (takeoff/land/etc. TBD) |
| 6 | 20 | unknown param (speed mode / trim?) constant so far |
| 7 | 20 | checksum = XOR of bytes 1..6  (verified on idle) |
| 8 | 99 | end |

## Telemetry (drone -> client)  payload 11 bytes, constant so far
cc 03 21 00 64 21 04 04 00 67 33  (0x64 = 100 -> battery %?; decode later)

## Open items / findings
- App displayed "weak GPS signal, flight restricted" and refused to send takeoff. **The S20 Lite may HAVE GPS**
  (assumption "no GPS" is probably wrong). Takeoff needs GPS lock (go outdoors) or comes from app-side check.
- No takeoff/land/stick packets captured yet (app blocked takeoff).
- TODO: decode TCP 8060 / 7060 `lewei_cmd` handshake (does UDP need it first?).

## Milestone log
- M1 DONE: drone 192.168.0.1, control UDP :50000 (local :5010).
- M2 DONE (props off): python examples/neutral_heartbeat.py 5 -> sent 126 neutral frames, drone replied with
  telemetry cc03210064210404006733. UDP control works WITHOUT the TCP 8060/7060 handshake (app closed).
- Mac app shows "weak GPS" (Mac has no GPS chip); iPhone app does not. rvictl fails on macOS 26
  (bootstrap_look_up 1102) -> use captures/iphone_cap.py (pymobiledevice3 pcapd over USB, venv at .venv,
  needs construct==2.10.69).

## iPhone captures (192.168.0.20:5010 <-> 192.168.0.1:50000)  — 02_takeoff.pcap
command: neutral (iPhone)      packet: 66 80 80 80 80 00 00 00 99   (byte6 param = 00 here; Mac app had 20)
command: takeoff               packet: 66 80 80 80 80 01 00 01 99   destination 192.168.0.1:50000
send rate: repeated ~1 s (48 frames at ~22 ms, t=6.71..7.71 s), then back to neutral — held button, not latched
observed behavior: drone state byte went 00 -> 20 (taking off) -> 40 (flying) in telemetry. PROPS OFF.

Telemetry (11 bytes): cc 03 [b2] [state] 64 [b5] 04 04 00 [xor] 33 ; xor = bytes1..8 (verified on all 3 states)
- state (byte3): 00 idle/ground, 20 taking off, 40 flying/hover (lands -> TBD from capture 03)
- byte2: 21 (Mac capture) / 2a (iPhone capture) — unknown; byte5: 21 (Mac) / 01 (iPhone) — maybe GPS-ready bit; byte4 0x64 = battery?

## M3/M4 from Python (props off) — examples/takeoff_land.py
command: takeoff   packet 66 80 80 80 80 01 00 01 99 held 1 s -> telemetry ground->taking-off (0.16 s) -> flying (+2.15 s). WORKS.
command: land      packet 66 80 80 80 80 02 00 02 99 held 1 s. WORKS but with 3 s hover the 1st press did NOT land
                   (still 'flying' 4 s later); 2nd press -> ground 3 s later (iPhone capture: ground ~1 s after press).
                   Hypothesis A: land ignored while still climbing/short after takeoff. B: slow descent after short flight.
                   Test: run `takeoff_land.py 8` and compare time-to-ground.
Telemetry seen from Mac run: cc 03 4c 00 ff 00 04 04 00 xx 33 (byte2 4c/4b/2e, byte4 ff, byte5 00) vs iPhone runs
 byte4 64, byte5 01 -> possibly GPS/phone-related; unknown. TCP: app only sends 1 keepalive/s on :7060; no TCP at takeoff/land.

## Takeoff height
App warning text for one-key takeoff: "the drone will lift off and ascend automatically to a height of 1.2m above the ground."
(An earlier note of "10 m" was a mistaken reading; 10 m may belong to another feature, e.g. return/trajectory — unverified.)
Our TAKEOFF frame (flag 0x01) is that one-key takeoff; no altitude field in the 9-byte frame, height is fixed by firmware.
Props-on tests: open area, no payload first, tether/hands clear, land ready. Payload will lower hover margin at 1.2 m — test gradually.

## 04_pitch_fwd (iPhone, started already in flight; state 0x40 throughout)
command: pitch forward   packet (full): 66 80 80 ff 80 00 00 7f 99   byte3 = pitch axis, 0x80 center, forward = high
ramp (app): 80 -> ab -> c5 -> df -> fb -> fc -> fd -> fe -> ff over ~0.5 s (2.99-3.49 s), held ff ~6 s, then INSTANT back to 80.
destination 192.168.0.1:50000, repeated ~46 Hz. Other axes stayed 0x80. Checksum rule (xor bytes1-6) verified.
Telemetry did not change with pitch. Our library should use small values (e.g. 0x9f) and soft ramps.

## 06_roll_right (iPhone, props on, free flight): takeoff, rotate, left, down
CORRECTION: byte order is 1 roll, 2 pitch, 3 THROTTLE, 4 yaw (standard Lewei order). Capture 04 "pitch fwd" was throttle up.
Evidence: each stick moves two bytes that share a physical stick (yaw 4 + throttle 3 bleed; roll 1 + pitch 2 bleed),
and throttle (byte3) held down to 0x08 -> telemetry state 40 -> 00 (drone landed by throttle-down).
- takeoff t=6.21 (flag 01, held 1 s)
- rotate t=11.56-12.06: yaw byte4 80 -> cc = rotated RIGHT ~45 deg (user confirmed) => yaw right is ABOVE 0x80
- roll   t=13.15-13.82: roll byte1 80 -> e6 (+ pitch bleed 5d); drone slid RIGHT (user confirmed) => right is ABOVE 0x80
- down   t=16.06-18.88: throttle byte3 80 -> 08 -> drone landed at 18.76
Telemetry byte2 counts down steadily in flight (39 -> 19): likely battery level/voltage.
After t=30.8 the app sends other message types (a5 .. 5a, 68 ..) -- probably another screen (settings/trajectory). TODO.

## Video (TCP 192.168.0.1:7060, drone -> client)
Frames are `lewei_cmd` 46-byte headers: bytes 9-11 = 00 01 01 for video, bytes 22-25 = payload length (LE).
Payload = 32-byte sub-header, then plain **H.264 Annex-B** (SPS/PPS/IDR present), 1280x720. Not encrypted.
App sends a 46-byte `lewei_cmd` 00 01 00 request ~1/s on the same socket (keepalive / stream request).
First decode from 01_idle.pcap via ffmpeg: captures/first_decoded_frame.jpg (top half clean, bottom corrupted —
reassembly from capture, live socket should be clean).
- video.py + examples/watch.py: decoder + YOLOv8n person boxes verified OFFLINE on 01_idle stream (250 frames, ~31 fps detect).
  Live connection (send STREAM_REQUEST on TCP 7060, repeat 1/s) not yet tested against the drone.
- calibrate.py: pitch|roll|up|yaw one-push calibration flights; writes PITCH_FORWARD_SIGN and *_PER_S constants.
- Capture 11_connect (app startup): on TCP 7060 app sends cmd 0x01 then cmd 0x02 (46-byte headers, no payload);
  video (cmd 01 sub 01) starts ~0.65 s later. cmd 0x02 = START VIDEO. App also does 8060 cmds 0x04 (unix time),
  0x38, 0x25 (reply = device info incl. SSID), 0x06 -- not needed for video.

## Video bottom-half corruption (open problem)
Live + captured: top ~half of every frame decodes clean, then garbage (rows ~22-26 of 45). NOT a framing bug:
lewei message lengths exact, no TCP gaps, one NAL (single slice) per frame, sub-header = [keyframe u32][h264 len u32][ts u32][0][0][0x2000][0][0].
Keyframe (11_connect frame 0, 23894 B): MB progress smooth to byte ~13060 then stops (MB 2131) -> bytes altered mid-frame.
Header bytes 26-35 per frame: 81 00 00 00 + 6 changing bytes (key? checksum?). Tried: XOR with those bytes from ~12.9k (no fix),
hidden 2nd-slice header search (none). App (Mac/iOS) binary only 4 KB FairPlay-encrypted; has LWStreamFFmpegDecode,
GPUImageLwStreamHardwareDecodeSecond (hardwareDecodeFrame:::::::, h264_queue_second). Receive/unscramble code is stripped C;
next step = disassemble with Ghidra/radare2 starting from decodeThreadFun (0x1005054f8) / ffmpegDecodeFrame (0x1005423a8) callers.

## AP isolation test (2026-10-14): NONE -> Plan A (ESP32 as 2nd Wi-Fi client) works
Mac 192.168.0.21 pinged iPhone 192.168.0.20 (0% loss, 6-60 ms) and drone 192.168.0.1 (16-100 ms).
Broadcast ping to 192.168.0.255 answered by iPhone -> broadcast discovery of the harness ESP32 will work.
Drone AP MAC a4:6b:40:bd:8f:c9.

## Video bottom-half corruption: SOLVED (2026-10-16)
App video loop (func 0x1004d0e54): if lewei header u32 @26 == 0x81, call 0x1004f4954(h264 + len/2, k1, k2, k3)
with k1,k2,k3 = u16 LE from header bytes 30,32,34. That function restores 3 bytes at the MIDPOINT of the H.264 data
(after the 32-byte sub-header):  b0 = i where T1[i]==k1;  b1 = (i where T2[i]==k2) ^ b0;  b2 = (i where T3[i]==k3) ^ b0 ^ b1.
Tables T1/T2/T3 (256 x u16) live in the app's __data at 0x101f50f88 / 0x101f51188 / 0x101f51388 -> video_tables.py.
(Flag == 1 path: app instead inverts one byte at an index from 0x1004f4aac -- not seen in our captures, not implemented.)
Result on 11_connect: 176/176 frames flag 0x81; ffmpeg errors 148 -> 0; full clean frames. Implemented in video.unscramble().
captures/11_connect_restored.mp4 = restored clip. follow_yaw --top default now 1.0 (full frame).

## AI vision (OpenAI) for find_and_dip.py
ai_vision.py: two engines with one interface (submit/latest). Default "decisions" = OpenAI Decisions API
(POST /v1/decisions, gpt-6-luna only): questions = predicate visible, choice horizontal (7 positions + not_visible),
choice vertical (5 + not_visible), score size (5 levels); x/y/size = probability-weighted averages.
"responses" engine = Responses API + JSON schema (x, y, size, confidence, note), any model (default gpt-6-luna).
Request/parse verified with a mocked HTTP transport (correct endpoint + payload); not yet run against the real API.
- macOS 26 GOTCHA: a Python process that does a system proxy lookup (urllib getproxies / httpx trust_env) or TLS via
  Apple's trust store (truststore, used by the OpenAI SDK by default) LOSES local-network access -> drone TCP 7060 / UDP
  50000 time out for the rest of that process. Fix in ai_vision.make_client(): DefaultHttpxClient(trust_env=False,
  verify=ssl ctx from certifi). Verified: drone + API interleave fine; default client still breaks it.
- Also: macOS may auto-switch Wi-Fi back to a known home network (drone has no internet) -> turn off Auto-Join while flying.

## Camera tilt over Wi-Fi: NOT supported (tested 2026-10-16)
App has a richer control packet `68 01 0d <13 bytes> <xor>` (seen in capture 06 after t=30 s; payload = the app's
debug struct: Roll,Pitch,Thro,Yaw bytes; TrimRoll/TrimPitch 6 bits; flag bits 44-59; PTZ_H 60-61; PTZ_V 62-63;
CtrlPanel/display/LightOn 64-66; xor = XOR of type,len,payload). examples/tilt_test.py sent it with PTZ_V=1/2/3,
PTZ_H=1/2, LightOn=1 (motors off): no camera movement (phase-correlation shift within noise) and no light change ->
S20 Lite appears to ignore 0x68 packets entirely. Physical remote DOES tilt the camera on the ground, in discrete
jerky steps (button-step servo/stepper). Tilt is RC-radio only. Workaround: pre-tilt with the remote before flying.
Possible hardware route: ESP32 "pressing" the remote's Camera Up/Down buttons via optocoupler (not done).
- find_and_dip.py: --height M (needs calibrate.py up) / --height-s S (seconds at 20% throttle) before scanning.
  One height estimate (h20 = seconds at 20% throttle from takeoff) shared by HEIGHT, --vertical and DIP; floor/ceiling
  guard = --v-budget (uncalibrated) or calibration MIN/MAX_HEIGHT_M. Every run logs to captures/missions/<ts>_<target>/
  (events.jsonl incl. raw AI answers, ai/NNNN.jpg frames, contact.jpg grid, summary.txt).

## Payload harness: ESP-NOW (2026-10-18)
Drone Wi-Fi is 5 GHz-only; ESP32-C3 is 2.4 GHz-only -> harness can't join the drone network (Plan A dead).
Plan B: ground XIAO on laptop USB (firmware/ground) <-> ESP-NOW broadcast ch 1, protocol 11b/g/n+LR (LR-only heard
nothing) <-> harness XIAO (firmware/harness). Text frames "AMH1 <seq> <cmd>" / "AMH1R <seq> <reply>" / heartbeat
"AMH1H <state>" 1 Hz; harness repeats last reply for a repeated seq (safe retries). Python: harness.Harness.discover().
Test: all commands + arm timeout OK, but RSSI -93/-94 dBm with boards side by side (NO ANTENNAS) and a PING was lost
after 4 retries -> fit U.FL 2.4 GHz antennas on both boards before flying.
- Harness firmware: SETHOLD n / SETRELEASE n / ANGLES (angles saved in flash via Preferences; verified across reset).
  examples/servo_bench.py = interactive tuning (radio or --usb). route.py step "release" and find_and_dip.py --release
  (prepare_for_flight() before takeoff refuses to fly without harness; safe_release() never raises, disarms on failure).
  Verified end-to-end over ESP-NOW: prepare_for_flight -> safe_release RELEASED -> CLOSE (signal -86 dBm, no antennas).
- XIAO C3 gotcha: remote reset via RTS from pyserial can drop the board into download mode -> tap R to run again.
  If upload fails ("No serial data received"): hold B, tap R, release B, upload, then tap R.
- 2026-10-20: ground antenna (long PCB strip, U.FL) on ground XIAO only: signal -84/-94 -> -53..-65 dBm side by side.
  Bug found+fixed: harness on USB with nobody reading stalled on Serial.printf (HWCDC TX timeout) and missed commands
  (9/50) -> Serial.setTxTimeoutMs(0). After fix: 47/50 single-try, ~100% with retries.

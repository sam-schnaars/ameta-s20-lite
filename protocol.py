"""Lewei-style control frame for the AMETA S20 Lite (derived from iPhone captures, see notes.md)."""
import socket

DRONE_IP = "192.168.0.1"
DRONE_PORT = 50000
LOCAL_PORT = 5010          # the official app binds 5010; drone replies to it
SEND_HZ = 45               # app sends ~46 frames/s
CENTER = 0x80

FLAG_NONE = 0x00
FLAG_TAKEOFF = 0x01       # held ~1 s (48 frames) in capture 02
FLAG_LAND = 0x02          # held ~1 s (49 frames) in capture 03

# telemetry byte 3 (drone -> client)
STATE_GROUND = 0x00
STATE_TAKING_OFF = 0x20
STATE_FLYING = 0x40


def checksum(frame: bytes) -> int:
    x = 0
    for b in frame[1:7]:
        x ^= b
    return x


def build_frame(roll=CENTER, pitch=CENTER, throttle=CENTER, yaw=CENTER, flags=FLAG_NONE, param=0x00) -> bytes:
    # Byte order from capture 06 (same-stick bleed + throttle-down landed the drone):
    #   1 roll, 2 pitch, 3 throttle, 4 yaw.  (Capture 04 "pitch fwd" was actually THROTTLE up.)
    body = bytes([0x66, roll, pitch, throttle, yaw, flags, param])
    return body + bytes([checksum(body), 0x99])


NEUTRAL = build_frame()
TAKEOFF = build_frame(flags=FLAG_TAKEOFF)
LAND = build_frame(flags=FLAG_LAND)
assert NEUTRAL == bytes.fromhex("668080808000000099"), NEUTRAL.hex()
assert TAKEOFF == bytes.fromhex("668080808001000199"), TAKEOFF.hex()
assert LAND == bytes.fromhex("668080808002000299"), LAND.hex()


def parse_telemetry(data: bytes):
    """Return state byte if `data` is a valid 11-byte telemetry packet, else None."""
    if len(data) != 11 or data[0] != 0xCC or data[10] != 0x33:
        return None
    x = 0
    for b in data[1:9]:
        x ^= b
    return data[3] if x == data[9] else None


def open_socket(timeout=0.02) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("", LOCAL_PORT))
    s.settimeout(timeout)
    return s


# ---- stick axes --------------------------------------------------------------
# Directions: +1 if that direction makes the byte go ABOVE 0x80, -1 if below, None = unconfirmed.
# Capture 06: roll went UP to 0xe6 and the drone slid RIGHT (user confirmed) -> right is ABOVE 0x80.
ROLL_AXIS = "roll"
ROLL_RIGHT_SIGN = +1
PITCH_FORWARD_SIGN = None   # pitch byte 2 never cleanly isolated yet -> forward()/back() disabled
YAW_RIGHT_SIGN = +1         # capture 06: rotated right ~45 deg, yaw byte 80 -> cc

MAX_SPEED = 0.5            # safety cap: never send more than half stick from code


def stick_value(speed: float) -> int:
    """-1..+1 -> stick byte (0x80 center, 0xff full positive). Clamped to +/-MAX_SPEED.
    Positive side confirmed (pitch forward reaches 0xff); negative side assumed symmetric until capture 05."""
    speed = max(-MAX_SPEED, min(MAX_SPEED, speed))
    if speed >= 0:
        return min(0xFF, round(CENTER + speed * 0x7F))
    return max(0x01, round(CENTER + speed * 0x7F))

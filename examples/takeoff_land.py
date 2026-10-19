"""First flight-command test: takeoff -> hover 3 s -> land. PROPS OFF.

Needs: Mac joined to the drone Wi-Fi, AMETA app CLOSED on every device (iPhone too).
Ctrl-C at any time sends LAND. Neutral frames are sent continuously in between.
"""
import os, socket, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import protocol as P

HOVER_S = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0   # usage: takeoff_land.py [hover_seconds]
HOLD_S = 1.0           # how long the app holds the takeoff/land flag
ADDR = (P.DRONE_IP, P.DRONE_PORT)

sock = P.open_socket()
frame = P.NEUTRAL            # the single place a command is set; reverts to neutral on its own
state = None
stop = False
T0 = time.time()
log = []                     # (t, event) timeline printed at the end
lock = threading.Lock()


def loop():
    global state
    while not stop:
        with lock:
            f = frame
        sock.sendto(f, ADDR)
        t_end = time.time() + 1 / P.SEND_HZ
        while time.time() < t_end:
            try:
                raw = sock.recvfrom(64)[0]
                s = P.parse_telemetry(raw)
                if s is not None:
                    if s != state:
                        log.append((time.time() - T0, f"telemetry state -> {name(s)} (raw {raw.hex()})"))
                    state = s
            except socket.timeout:
                pass


def press(f, seconds):
    global frame
    with lock:
        frame = f
    log.append((time.time() - T0, f"press {f.hex()}"))
    time.sleep(seconds)
    with lock:
        frame = P.NEUTRAL


def wait_state(want, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if state == want:
            return True
        time.sleep(0.05)
    return False


def name(s):
    return {None: "none", P.STATE_GROUND: "ground", P.STATE_TAKING_OFF: "taking-off",
            P.STATE_FLYING: "flying"}.get(s, f"0x{s:02x}")


print("NOTE: the takeoff frame is the app's one-key takeoff (app text: auto-ascends to 1.2 m above ground).")
print("      Props-ON tests: open area, no payload first, hands clear, land command ready.")
if input("PROPS REMOVED and drone on a table? type 'yes': ").strip().lower() != "yes":
    sys.exit("aborted")

t = threading.Thread(target=loop, daemon=True)
t.start()
try:
    if not wait_state(P.STATE_GROUND, 3):
        sys.exit(f"abort: expected telemetry state 'ground', saw {name(state)} "
                 "(no telemetry = not on drone Wi-Fi or app still open)")
    print("telemetry ok, state=ground. TAKEOFF")
    press(P.TAKEOFF, HOLD_S)
    ok = wait_state(P.STATE_FLYING, 6)
    print(f"state after takeoff: {name(state)}" + ("" if ok else "  (!) never reached flying"))
    print(f"hovering {HOVER_S:.0f} s")
    time.sleep(HOVER_S)
finally:
    print("LAND")
    ok = False
    for attempt in range(1, 4):          # re-press land up to 3x if the drone doesn't report ground
        press(P.LAND, HOLD_S)
        ok = wait_state(P.STATE_GROUND, 3)
        if ok:
            break
        print(f"  land attempt {attempt}: still {name(state)}, retrying")
    print(f"state after land: {name(state)}" + ("" if ok else "  (!) did not report ground — press land in the app / unplug battery"))
    stop = True
    t.join(1)
    print("--- timeline ---")
    for tt, ev in log:
        print(f"{tt:6.2f}s  {ev}")

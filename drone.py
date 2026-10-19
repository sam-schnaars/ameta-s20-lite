"""High-level wrapper for the AMETA S20 Lite. Sends control frames continuously (~45 Hz) in a
background thread; commands only change what that thread sends. See notes.md for the protocol.

    with S20Lite() as drone:      # connects; on ANY exception / Ctrl-C it lands
        drone.takeoff()           # one-key takeoff: firmware climbs to ~1.2 m and holds
        drone.right(speed=0.2, duration=1.0)
        drone.land()
"""
import socket, threading, time

import protocol as P


class S20Lite:
    def __init__(self, verbose=True):
        self.verbose = verbose
        self.sock = None
        self.state = None
        self._axes = dict(roll=P.CENTER, pitch=P.CENTER, throttle=P.CENTER, yaw=P.CENTER)
        self._flags = P.FLAG_NONE
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._t0 = time.time()

    # ---- plumbing ----------------------------------------------------------
    def log(self, msg):
        if self.verbose:
            print(f"{time.time() - self._t0:6.2f}s  {msg}", flush=True)

    def _loop(self):
        addr = (P.DRONE_IP, P.DRONE_PORT)
        while not self._stop.is_set():
            with self._lock:
                frame = P.build_frame(flags=self._flags, **self._axes)
            self.sock.sendto(frame, addr)
            t_end = time.time() + 1 / P.SEND_HZ
            while time.time() < t_end:
                try:
                    s = P.parse_telemetry(self.sock.recvfrom(64)[0])
                    if s is not None:
                        if s != self.state:
                            self.log(f"telemetry state -> {self.state_name(s)}")
                        self.state = s
                except socket.timeout:
                    pass

    @staticmethod
    def state_name(s):
        return {None: "none", P.STATE_GROUND: "ground", P.STATE_TAKING_OFF: "taking-off",
                P.STATE_FLYING: "flying"}.get(s, f"0x{s:02x}")

    def wait_state(self, want, timeout):
        end = time.time() + timeout
        while time.time() < end:
            if self.state == want:
                return True
            time.sleep(0.05)
        return False

    def _press(self, flag, seconds=1.0):
        with self._lock:
            self._flags = flag
        time.sleep(seconds)
        with self._lock:
            self._flags = P.FLAG_NONE

    # ---- public API ----------------------------------------------------------
    def connect(self, timeout=3):
        self.sock = P.open_socket()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        if self.state is None and not self.wait_state(P.STATE_GROUND, timeout) and self.state is None:
            self.close()
            raise RuntimeError("no telemetry: Mac not on drone Wi-Fi, or the AMETA app is still open somewhere")
        self.log(f"connected, state={self.state_name(self.state)}")

    def takeoff(self, settle=4.0):
        if self.state != P.STATE_GROUND:
            raise RuntimeError(f"refusing takeoff: state is {self.state_name(self.state)}, expected ground")
        self.log("TAKEOFF")
        self._press(P.FLAG_TAKEOFF)
        if not self.wait_state(P.STATE_FLYING, 8):
            raise RuntimeError("drone never reported flying")
        self.log(f"flying; settling {settle:.0f} s at ~1.2 m")
        time.sleep(settle)   # land was ignored once when sent 3 s after 'flying'; give the climb time to finish

    def land(self, attempts=3):
        for i in range(1, attempts + 1):
            self.log(f"LAND (attempt {i})")
            self.stop()
            self._press(P.FLAG_LAND)
            if self.wait_state(P.STATE_GROUND, 6):
                self.log("landed")
                return True
        self.log("(!) drone did not report ground — use the app or pull the battery")
        return False

    def stop(self):
        """All sticks to center immediately (the app also releases instantly)."""
        with self._lock:
            for k in self._axes:
                self._axes[k] = P.CENTER

    def _move(self, axis, value, duration, ramp=0.3):
        if axis is None:
            raise RuntimeError("this axis is not decoded yet (see protocol.py ROLL_AXIS)")
        if self.state != P.STATE_FLYING:
            raise RuntimeError(f"refusing to move: state is {self.state_name(self.state)}")
        self.log(f"{axis} -> 0x{value:02x} for {duration:.2f} s")
        steps = max(1, int(ramp * P.SEND_HZ))
        for i in range(1, steps + 1):             # soft ramp like the app (80 -> target in ~0.3-0.5 s)
            with self._lock:
                self._axes[axis] = round(P.CENTER + (value - P.CENTER) * i / steps)
            time.sleep(ramp / steps)
        time.sleep(max(0.0, duration - ramp))
        self.stop()
        self.log(f"{axis} released")

    def forward(self, speed=0.2, duration=1.0):
        if P.PITCH_FORWARD_SIGN is None:
            raise RuntimeError("pitch direction not confirmed yet (capture pitch forward)")
        self._move("pitch", P.stick_value(speed * P.PITCH_FORWARD_SIGN), duration)

    def back(self, speed=0.2, duration=1.0):
        if P.PITCH_FORWARD_SIGN is None:
            raise RuntimeError("pitch direction not confirmed yet (capture pitch forward)")
        self._move("pitch", P.stick_value(-speed * P.PITCH_FORWARD_SIGN), duration)

    def right(self, speed=0.2, duration=1.0):
        self._move(P.ROLL_AXIS, P.stick_value(speed * P.ROLL_RIGHT_SIGN), duration)

    def left(self, speed=0.2, duration=1.0):
        self._move(P.ROLL_AXIS, P.stick_value(-speed * P.ROLL_RIGHT_SIGN), duration)

    def up(self, speed=0.2, duration=1.0):
        self._move("throttle", P.stick_value(speed), duration)

    def down(self, speed=0.2, duration=1.0):
        self._move("throttle", P.stick_value(-speed), duration)

    def rotate_right(self, speed=0.2, duration=1.0):
        self._move("yaw", P.stick_value(speed * P.YAW_RIGHT_SIGN), duration)

    def rotate_left(self, speed=0.2, duration=1.0):
        self._move("yaw", P.stick_value(-speed * P.YAW_RIGHT_SIGN), duration)

    def set_stick(self, axis, speed):
        """Set one stick continuously (-1..1, clamped to MAX_SPEED) until changed or stop().
        For closed-loop control; the caller must keep updating it or call stop()."""
        if self.state != P.STATE_FLYING:
            self.stop()
            raise RuntimeError(f"refusing stick input: state is {self.state_name(self.state)}")
        sign = {"yaw": P.YAW_RIGHT_SIGN, "roll": P.ROLL_RIGHT_SIGN}.get(axis, 1)
        with self._lock:
            self._axes[axis] = P.stick_value(speed * sign)

    def hover(self, seconds):
        self.stop()
        self.log(f"hover {seconds:.1f} s")
        time.sleep(seconds)

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(1)
        if self.sock:
            self.sock.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is not None and self.state in (P.STATE_TAKING_OFF, P.STATE_FLYING):
                self.log(f"!! {exc_type.__name__}: {exc} -> emergency LAND")
                self.land()
        finally:
            self.close()
        return False

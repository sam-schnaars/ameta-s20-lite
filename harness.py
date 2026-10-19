"""Talk to the ESP32 payload harness.

The S20 Lite's Wi-Fi is 5 GHz-only and the ESP32-C3 is 2.4 GHz-only, so the harness can't join the drone's
network. Instead a second XIAO on the laptop's USB (firmware/ground) relays commands over ESP-NOW:

    from harness import Harness
    h = Harness.discover()      # finds the ground station on USB and waits for the harness's heartbeat
    h.arm(); h.release()        # -> True once the harness confirms RELEASED
    h.close()                   # latch back to hold

WifiHarness (bottom) is the original direct-UDP version, for drones with 2.4 GHz Wi-Fi.
"""
import glob, random, socket, threading, time

CMD_PORT = 6000
ANNOUNCE_PORT = 6001


class WifiHarness:
    def __init__(self, ip, timeout=0.5, retries=3):
        self.ip, self.retries = ip, retries
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(timeout)

    @classmethod
    def discover(cls, timeout=10):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", ANNOUNCE_PORT))
        s.settimeout(timeout)
        try:
            data, (ip, _) = s.recvfrom(128)
        except socket.timeout:
            raise RuntimeError("no harness found: is it powered and on the drone's Wi-Fi?")
        finally:
            s.close()
        print(f"harness found at {ip}: {data.decode(errors='replace')}")
        return cls(ip)

    def send(self, cmd):
        """Send a command, return the reply (retries on packet loss)."""
        for _ in range(self.retries):
            self.sock.sendto(cmd.encode(), (self.ip, CMD_PORT))
            try:
                return self.sock.recvfrom(128)[0].decode().strip()
            except socket.timeout:
                continue
        raise RuntimeError(f"harness did not answer {cmd!r}")

    def ping(self):
        return self.send("PING")

    def arm(self):
        r = self.send("ARM")
        if r != "ARMED":
            raise RuntimeError(f"arm failed: {r}")

    def release(self):
        r = self.send("RELEASE")
        if r != "RELEASED":
            raise RuntimeError(f"release failed: {r}")
        return True

    def close(self):
        return self.send("CLOSE")

    def angle(self, a):
        return self.send(f"ANGLE {int(a)}")


class Harness:
    """Harness reached through the ground-station XIAO (USB serial <-> ESP-NOW)."""

    def __init__(self, port, timeout=0.6, retries=4):
        import serial                                  # pyserial (in .venv)
        self.ser = serial.Serial(port, 115200, timeout=0.05)
        self.timeout, self.retries = timeout, retries
        self.seq = random.randint(1000, 900000)        # never collides with a previous run's numbers
        self.last_hello = None                         # (state, rssi, time)
        self._replies = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        buf = b""
        while not self._stop.is_set():
            try:
                buf += self.ser.read(256)
            except Exception:
                return
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                t = line.decode(errors="replace").strip().split(" ")
                if t[0] == "R" and len(t) >= 3:
                    with self._lock:
                        self._replies[t[1]] = " ".join(t[2:])
                elif t[0] == "HELLO" and len(t) >= 2:
                    self.last_hello = (t[1], int(t[2]) if len(t) > 2 and t[2].lstrip("-").isdigit() else None, time.time())

    @staticmethod
    def find_ground_port():
        import serial
        for port in sorted(glob.glob("/dev/cu.usbmodem*")):
            try:
                with serial.Serial(port, 115200, timeout=0.3) as s:
                    time.sleep(0.3); s.reset_input_buffer()
                    s.write(b"WHO\n"); time.sleep(0.4)
                    if b"GROUND" in s.read(400):
                        return port
            except Exception:
                continue
        return None

    @classmethod
    def discover(cls, timeout=10):
        port = cls.find_ground_port()
        if not port:
            raise RuntimeError("no ground station found: plug the ground XIAO (firmware/ground) into USB")
        h = cls(port)
        end = time.time() + timeout
        while time.time() < end:
            if h.last_hello and time.time() - h.last_hello[2] < 2:
                st, rssi, _ = h.last_hello
                print(f"harness found via ground station {port}: state={st} signal={rssi} dBm")
                return h
            time.sleep(0.1)
        h.close_link()
        raise RuntimeError("ground station OK but no harness heartbeat: is the harness switched on and nearby?")

    def link_ok(self, max_age=2.5):
        return self.last_hello is not None and time.time() - self.last_hello[2] < max_age

    def send(self, cmd):
        """Send a command, return the harness's reply. Retries reuse the same seq, so a command that
        already ran (reply lost) is answered again without running twice."""
        self.seq += 1
        key = str(self.seq)
        for _ in range(self.retries):
            self.ser.write(f"{key} {cmd}\n".encode())
            end = time.time() + self.timeout
            while time.time() < end:
                with self._lock:
                    if key in self._replies:
                        return self._replies.pop(key)
                time.sleep(0.01)
        raise RuntimeError(f"harness did not answer {cmd!r} (out of radio range?)")

    def ping(self):
        return self.send("PING")

    def arm(self):
        r = self.send("ARM")
        if r != "ARMED":
            raise RuntimeError(f"arm failed: {r}")

    def release(self):
        r = self.send("RELEASE")
        if r != "RELEASED":
            raise RuntimeError(f"release failed: {r}")
        return True

    def close(self):
        return self.send("CLOSE")

    def angle(self, a):
        return self.send(f"ANGLE {int(a)}")

    def close_link(self):
        self._stop.set()
        try:
            self.ser.close()
        except Exception:
            pass


# ---- helpers used by the mission scripts ---------------------------------------------------------
def prepare_for_flight(timeout=10):
    """Before takeoff: find the harness via the ground station, make sure the latch is CLOSED and the
    radio link answers. Raises RuntimeError (caller should refuse to fly) if anything is off."""
    h = Harness.discover(timeout=timeout)
    r = h.close()
    if r != "CLOSED":
        raise RuntimeError(f"harness did not close the latch: {r}")
    print(f"harness ready: latch CLOSED, signal {h.last_hello[1]} dBm")
    return h


def safe_release(h):
    """ARM then RELEASE. Never raises: returns (released: bool, message). Refuses without a live heartbeat
    and disarms again if anything goes wrong, so a half-done release can't fire later."""
    if not h.link_ok():
        return False, "no harness heartbeat (out of radio range?) -- release skipped"
    try:
        h.arm()
        h.release()
        return True, "RELEASED (confirmed by harness)"
    except RuntimeError as e:
        try:
            h.send("DISARM")
        except RuntimeError:
            pass
        return False, f"release failed: {e}"

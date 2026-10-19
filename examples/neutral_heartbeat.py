"""Milestone 2: send ONLY the neutral frame at ~45 Hz for N seconds and print telemetry. PROPS OFF."""
import sys, time, os, socket
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import protocol

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 5
s = protocol.open_socket()
end, seen, sent = time.time() + secs, set(), 0
while time.time() < end:
    s.sendto(protocol.NEUTRAL, (protocol.DRONE_IP, protocol.DRONE_PORT)); sent += 1
    try:
        data, _ = s.recvfrom(256); seen.add(data.hex())
    except socket.timeout:
        pass
    time.sleep(0.022)
print(f"sent {sent} neutral frames; distinct telemetry: {seen or 'none'}")

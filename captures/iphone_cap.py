"""Capture an iPhone's network traffic over USB (no rvictl) to captures/<name>.pcap.
usage: .venv/bin/python captures/iphone_cap.py <name> [seconds]   (iPhone plugged in + trusted, unlocked)"""
import sys, time, os, threading
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.pcapd import PcapdService

name = sys.argv[1]; secs = float(sys.argv[2]) if len(sys.argv) > 2 else 30
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".pcap")
svc = PcapdService(create_using_usbmux())
end = time.time() + secs
print(f">>> Capturing {secs:.0f} s to {name}.pcap — do the action NOW", flush=True)

def gen():
    for pkt in svc.watch():
        yield pkt
        if time.time() > end:
            return

with open(out, "wb") as f:
    PcapdService.write_to_pcap(f, gen())
print(f">>> Done: {out}")

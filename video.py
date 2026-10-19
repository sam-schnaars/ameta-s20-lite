"""Live video from the AMETA S20 Lite (TCP 192.168.0.1:7060), decoded to numpy frames.

Wire format (see notes.md): every message starts with a 46-byte `lewei_cmd` header
    0-9   b"lewei_cmd\\0"
    10    command (0x01 = video channel)
    11    sub-type (0x01 = video frame, 0x00 = request/status)
    22-25 payload length, little-endian
Video payload = 32-byte sub-header + H.264 Annex-B with 3 bytes scrambled mid-frame (see unscramble()). The app keeps the stream alive by
sending an empty command-0x01 request about once a second; video starts after command 0x02.

This module only reads video; it never sends flight commands, so it is safe to run next to drone.py.
"""
import socket, threading, time

import av

from video_tables import T1, T2, T3

DRONE_IP = "192.168.0.1"
VIDEO_PORT = 7060
MAGIC = b"lewei_cmd\x00"
HEADER_LEN = 46
VIDEO_SUBHEADER_LEN = 32


def header(cmd, sub=0x00, length=0):
    h = bytearray(HEADER_LEN)
    h[0:10] = MAGIC
    h[10], h[11] = cmd, sub
    h[22:26] = length.to_bytes(4, "little")
    return bytes(h)


STREAM_REQUEST = header(0x01)   # byte-identical to the app's request in the captures
START_VIDEO = header(0x02)      # app sends this right after the first request (capture 11_connect)
assert STREAM_REQUEST.hex() == "6c657765695f636d64000100" + "00" * 34
assert START_VIDEO.hex() == "6c657765695f636d64000200" + "00" * 34


def iter_messages(read):
    """Yield (header, payload) from a byte source. `read(n)` returns up to n bytes, b'' at EOF."""
    buf = bytearray()
    while True:
        i = buf.find(MAGIC)
        if i < 0 or len(buf) - i < HEADER_LEN:
            if i > 0:
                del buf[:i]                     # drop junk before the next header
            elif i < 0 and len(buf) > len(MAGIC):
                del buf[:len(buf) - len(MAGIC)]
            chunk = read(65536)
            if not chunk:
                return
            buf += chunk
            continue
        if i:
            del buf[:i]
        length = int.from_bytes(buf[22:26], "little")
        if length > 4_000_000:                  # corrupt header; resync
            del buf[:len(MAGIC)]
            continue
        while len(buf) < HEADER_LEN + length:
            chunk = read(65536)
            if not chunk:
                return
            buf += chunk
        head = bytes(buf[:HEADER_LEN])
        payload = bytes(buf[HEADER_LEN:HEADER_LEN + length])
        del buf[:HEADER_LEN + length]
        yield head, payload


_INV = [{v: i for i, v in enumerate(t)} for t in (T1, T2, T3)]
FLAG_SCRAMBLED = 0x81


def unscramble(head, h264):
    """The drone overwrites 3 bytes at the middle of each H.264 frame and puts three encoded
    u16 keys in header bytes 30-35 (flag 0x81 in bytes 26-29). Restore them like the app does
    (app function 0x1004f4954): b0 = inv1[k1], b1 = inv2[k2]^b0, b2 = inv3[k3]^b0^b1."""
    if int.from_bytes(head[26:30], "little") != FLAG_SCRAMBLED or len(h264) < 8:
        return h264
    k1, k2, k3 = (int.from_bytes(head[i:i + 2], "little") for i in (30, 32, 34))
    try:
        b0 = _INV[0][k1]
        b1 = _INV[1][k2] ^ b0
        b2 = _INV[2][k3] ^ b0 ^ b1
    except KeyError:
        return h264                      # unknown key: leave frame as-is
    buf = bytearray(h264)
    m = len(buf) // 2
    buf[m:m + 3] = bytes((b0, b1, b2))
    return bytes(buf)


def h264_chunks(messages):
    for head, payload in messages:
        if head[10] == 0x01 and head[11] == 0x01 and len(payload) > VIDEO_SUBHEADER_LEN:
            yield unscramble(head, payload[VIDEO_SUBHEADER_LEN:])


class Decoder:
    def __init__(self):
        self.codec = av.CodecContext.create("h264", "r")

    def frames(self, h264):
        """Feed H.264 bytes, yield BGR numpy frames (errors from damaged frames are skipped)."""
        try:
            for pkt in self.codec.parse(h264):
                for frame in self.codec.decode(pkt):
                    yield frame.to_ndarray(format="bgr24")
        except av.error.InvalidDataError:
            return


class LiveStream:
    """Connects to the drone and yields raw H.264 chunks. Keeps the stream alive with requests."""

    def __init__(self, ip=DRONE_IP, port=VIDEO_PORT, keepalive_s=1.0):
        self.ip, self.port, self.keepalive_s = ip, port, keepalive_s
        self.sock = None
        self._stop = threading.Event()

    def _keepalive(self):
        while not self._stop.wait(self.keepalive_s):
            try:
                self.sock.sendall(STREAM_REQUEST)
            except OSError:
                return

    def __iter__(self):
        self.sock = socket.create_connection((self.ip, self.port), timeout=5)
        self.sock.sendall(STREAM_REQUEST)
        self.sock.sendall(START_VIDEO)
        threading.Thread(target=self._keepalive, daemon=True).start()
        return h264_chunks(iter_messages(self.sock.recv))

    def close(self):
        self._stop.set()
        if self.sock:
            self.sock.close()


def file_chunks(path):
    """H.264 chunks from a saved drone->client TCP byte stream (for testing without the drone)."""
    f = open(path, "rb")
    return h264_chunks(iter_messages(f.read))

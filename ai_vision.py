"""Ask an OpenAI vision model where a described object is in the drone's camera frame.

    loc = make_locator("the yellow cabinet")     # needs OPENAI_API_KEY; engine="decisions" (default) or "responses"
    loc.submit(frame_bgr)                         # non-blocking; several requests run in parallel
    r = loc.latest(max_age=1.0)                   # newest answer for a frame <= 1 s old, or None

Each answer: found, x (-1 left .. +1 right), y (-1 top .. +1 bottom), size (target height / frame
height), confidence (0..1), note. The model is only the "eyes": flying stays in fast local loops.
"""
import base64, json, os, ssl, threading, time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import certifi
import cv2
from openai import DefaultHttpxClient, OpenAI

DEFAULT_MODEL = os.environ.get("OPENAI_VISION_MODEL", "gpt-6-luna")   # fast + cheap; override with --model

SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "x": {"type": "number", "description": "target centre, -1 = left edge, +1 = right edge"},
        "y": {"type": "number", "description": "target centre, -1 = top edge, +1 = bottom edge"},
        "size": {"type": "number", "description": "target height as a fraction of image height, 0..1"},
        "confidence": {"type": "number", "description": "0..1"},
        "note": {"type": "string", "description": "a few words on what you see"},
    },
    "required": ["found", "x", "y", "size", "confidence", "note"],
    "additionalProperties": False,
}

SYSTEM = ("You locate objects in frames from a small drone's forward camera. "
          "Report where the requested target is. If it is not clearly visible, set found=false and "
          "x=y=size=0. Never guess a position for something you cannot see.")


def make_client():
    """OpenAI client that leaves the drone reachable.

    On this Mac (macOS 26), once a process asks macOS for system proxy settings or uses Apple's
    Security framework for TLS, it loses access to local-network devices -- the drone's TCP video
    and UDP control stop working. So: no proxy lookup (trust_env=False) and plain OpenSSL
    certificate checking with certifi instead of the system trust store.
    """
    tls = ssl.create_default_context(cafile=certifi.where())
    return OpenAI(timeout=6.0, max_retries=0,
                  http_client=DefaultHttpxClient(trust_env=False, verify=tls))


@dataclass
class Result:
    found: bool
    x: float
    y: float
    size: float
    confidence: float
    note: str
    frame_time: float     # when the frame was captured
    latency: float        # seconds the API call took


class Locator:
    def __init__(self, target, model=DEFAULT_MODEL, max_in_flight=4, width=512):
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not set (export it in your shell first)")
        self.target, self.model, self.width = target, model, width
        self.client = make_client()
        self.pool = ThreadPoolExecutor(max_in_flight)
        self.max_in_flight = max_in_flight
        self._in_flight = 0
        self._lock = threading.Lock()
        self._latest = None
        self.calls = self.errors = 0
        self.last_error = ""
        self.on_result = None     # callback(seq, frame_time, jpg_bytes, result_or_None, raw_dict, error_str)
        self._seq = 0

    def busy(self):
        return self._in_flight >= self.max_in_flight

    def submit(self, frame_bgr):
        """Queue one frame for analysis. Returns False (dropped) if too many calls are pending."""
        with self._lock:
            if self._in_flight >= self.max_in_flight:
                return False
            self._in_flight += 1
        h, w = frame_bgr.shape[:2]
        small = cv2.resize(frame_bgr, (self.width, int(h * self.width / w)))
        ok, jpg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])
        jpg = jpg.tobytes()
        with self._lock:
            self._seq += 1
            seq = self._seq
        self.pool.submit(self._run, seq, jpg, time.time())
        return True

    def _run(self, seq, jpg, frame_time):
        """Call the engine, update the newest result, report to on_result. Engines implement _ask()."""
        t0 = time.time()
        r = raw = err = None
        try:
            r, raw = self._ask(base64.b64encode(jpg).decode(), frame_time)
            r.latency = time.time() - t0
            with self._lock:
                self.calls += 1
                if self._latest is None or r.frame_time > self._latest.frame_time:
                    self._latest = r          # keep the answer for the NEWEST frame, not the newest reply
        except Exception as e:                # network/API trouble -> no new answer (control loop holds)
            err = f"{type(e).__name__}: {e}"[:300]
            with self._lock:
                self.errors += 1
                self.last_error = err[:120]
        finally:
            with self._lock:
                self._in_flight -= 1
        if self.on_result:
            try:
                self.on_result(seq, frame_time, jpg, r, raw, err)
            except Exception:
                pass

    def _ask(self, b64, frame_time):
        resp = self.client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": [
                    {"type": "input_text", "text": f"Target: {self.target}"},
                    {"type": "input_image", "detail": "low", "image_url": f"data:image/jpeg;base64,{b64}"},
                ]},
            ],
            text={"format": {"type": "json_schema", "name": "location", "strict": True, "schema": SCHEMA}},
        )
        d = json.loads(resp.output_text)
        r = Result(bool(d["found"]), max(-1, min(1, float(d["x"]))), max(-1, min(1, float(d["y"]))),
                   max(0, min(1, float(d["size"]))), float(d["confidence"]), str(d["note"])[:80],
                   frame_time, 0.0)
        return r, d

    def latest(self, max_age=1.0):
        with self._lock:
            r = self._latest
        if r is None or time.time() - r.frame_time > max_age:
            return None
        return r

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)


# ---- Decisions API engine (/v1/decisions, gpt-6-luna only) ------------------------------------
# Instead of generating JSON, the model answers fixed questions and returns a probability for every
# option. Positions are the probability-weighted average of the options, so they come out smooth.
H_CHOICES = [("far_left", -0.85), ("left", -0.55), ("center_left", -0.25), ("center", 0.0),
             ("center_right", 0.25), ("right", 0.55), ("far_right", 0.85)]
V_CHOICES = [("top", -0.75), ("upper", -0.35), ("middle", 0.0), ("lower", 0.35), ("bottom", 0.75)]
SIZE_LEVELS = [("tiny", 0.05), ("small", 0.15), ("medium", 0.3), ("large", 0.5), ("fills_frame", 0.8)]


def _weighted(answer, table, key):
    """Probability-weighted position from a choice/score answer; ignores 'not_visible'."""
    pos = dict(table)
    tot = val = 0.0
    for p in answer.probabilities:
        name = getattr(p, key)
        if name in pos:
            tot += p.probability
            val += p.probability * pos[name]
    return (val / tot if tot > 0 else 0.0), tot


class DecisionLocator(Locator):
    """Same interface as Locator (submit / latest / close), backed by client.decisions.create."""

    def __init__(self, target, model="gpt-6-luna", **kw):
        super().__init__(target, model="gpt-6-luna", **kw)   # Decisions API only supports gpt-6-luna
        t = target
        self.questions = [
            {"type": "predicate", "name": "visible",
             "instructions": f"The drone camera image clearly shows {t}."},
            {"type": "choice", "name": "horizontal",
             "instructions": f"Where is {t} horizontally in the image? Pick not_visible if it is not in view.",
             "choices": [{"value": v} for v, _ in H_CHOICES] + [{"value": "not_visible"}]},
            {"type": "choice", "name": "vertical",
             "instructions": f"Where is {t} vertically in the image? Pick not_visible if it is not in view.",
             "choices": [{"value": v} for v, _ in V_CHOICES] + [{"value": "not_visible"}]},
            {"type": "score", "name": "size",
             "instructions": f"How much of the image height does {t} take up? Use tiny if it is not visible.",
             "levels": [{"label": lbl} for lbl, _ in SIZE_LEVELS]},
        ]

    def _ask(self, b64, frame_time):
        d = self.client.decisions.create(
            model="gpt-6-luna",
            input=[{"role": "user", "content": [
                {"type": "input_text", "text": "Frame from a small drone's forward camera."},
                {"type": "input_image", "detail": "low", "image_url": f"data:image/jpeg;base64,{b64}"},
            ]}],
            questions=self.questions,
        )
        a = {ans.name: ans for ans in d.answers}
        raw = {n: ans.model_dump() for n, ans in a.items()}
        if any(getattr(x, "type", "") == "refusal" for x in a.values()):
            raise RuntimeError(f"model refused a question: {raw}")
        p_vis = a["visible"].probability
        x, p_h = _weighted(a["horizontal"], H_CHOICES, "value")
        y, _ = _weighted(a["vertical"], V_CHOICES, "value")
        size, _ = _weighted(a["size"], SIZE_LEVELS, "label")
        confidence = min(p_vis, p_h)        # visible AND located horizontally
        r = Result(confidence >= 0.5, x, y, size, confidence,
                   f"vis {p_vis:.2f} h={a['horizontal'].choice} v={a['vertical'].choice}", frame_time, 0.0)
        return r, raw


def make_locator(target, engine="decisions", model=DEFAULT_MODEL, **kw):
    return DecisionLocator(target, **kw) if engine == "decisions" else Locator(target, model=model, **kw)

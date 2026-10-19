"""Per-run mission log: captures/missions/<time>_<target>/

    events.jsonl   one JSON line per event: state changes, stick commands, every AI answer (raw + parsed)
    ai/0001.jpg    each exact frame the AI was shown (same number as its "seq" in events.jsonl)
    contact.jpg    grid of the AI frames labelled with confidence/position -- the quickest way to see
                   what the AI saw and why it did or didn't find the target
    summary.txt    counts, best confidence, state timeline
"""
import json, os, re, threading, time
from dataclasses import asdict

import cv2
import numpy as np


class MissionLog:
    def __init__(self, target, root=None, meta=None):
        root = root or os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures", "missions")
        slug = re.sub(r"[^a-z0-9]+", "_", target.lower()).strip("_")[:40]
        self.dir = os.path.join(root, time.strftime("%Y%m%d_%H%M%S") + "_" + slug)
        os.makedirs(os.path.join(self.dir, "ai"), exist_ok=True)
        self.t0 = time.time()
        self._lock = threading.Lock()
        self._f = open(os.path.join(self.dir, "events.jsonl"), "a")
        self.target = target
        self.ai_rows = []          # (seq, jpg_path, result or None, error)
        self.states = []
        self.event("start", target=target, **(meta or {}))

    def event(self, kind, **data):
        rec = {"t": round(time.time() - self.t0, 3), "event": kind, **data}
        with self._lock:
            self._f.write(json.dumps(rec, default=str) + "\n")
            self._f.flush()
        if kind == "state":
            self.states.append((rec["t"], data.get("state")))

    def ai(self, seq, frame_time, jpg, r, raw, err):
        """Hook for Locator.on_result."""
        path = os.path.join(self.dir, "ai", f"{seq:04d}.jpg")
        with open(path, "wb") as f:
            f.write(jpg)
        self.event("ai", seq=seq, frame_age_at_answer=round(time.time() - frame_time, 3),
                   result=asdict(r) if r else None, raw=raw, error=err)
        with self._lock:
            self.ai_rows.append((seq, path, r, err))

    def close(self, min_confidence=0.6):
        self.event("end")
        self._f.close()
        rows = sorted(self.ai_rows)
        found = [r for _, _, r, _ in rows if r and r.found and r.confidence >= min_confidence]
        best = max((r.confidence for _, _, r, _ in rows if r), default=0.0)
        errors = [e for *_, e in rows if e]
        lines = [f"target: {self.target}", f"AI answers: {len(rows) - len(errors)}  errors: {len(errors)}",
                 f"answers counted as FOUND (conf >= {min_confidence}): {len(found)}",
                 f"best confidence seen: {best:.2f}", "state timeline: " +
                 ", ".join(f"{s}@{t:.1f}s" for t, s in self.states)]
        if errors:
            lines.append("first error: " + errors[0])
        with open(os.path.join(self.dir, "summary.txt"), "w") as f:
            f.write("\n".join(lines) + "\n")
        self._contact_sheet(rows, min_confidence)
        return self.dir

    def _contact_sheet(self, rows, min_conf, cols=6, max_tiles=60, tw=256):
        if not rows:
            return
        step = max(1, len(rows) // max_tiles + (len(rows) % max_tiles > 0))
        tiles = []
        for seq, path, r, err in rows[::step]:
            img = cv2.imread(path)
            if img is None:
                continue
            h, w = img.shape[:2]
            img = cv2.resize(img, (tw, int(h * tw / w)))
            th = img.shape[0]
            if r is not None and r.found:
                cx, cy = int((r.x + 1) / 2 * tw), int((r.y + 1) / 2 * th)
                half = int(max(0.05, r.size) * th / 2)
                good = r.confidence >= min_conf
                cv2.rectangle(img, (cx - half, cy - half), (cx + half, cy + half),
                              (0, 255, 0) if good else (0, 200, 255), 2)
            label = f"#{seq} " + ("ERR" if err else f"conf {r.confidence:.2f} x{r.x:+.1f}")
            cv2.rectangle(img, (0, 0), (tw, 18), (0, 0, 0), -1)
            cv2.putText(img, label, (3, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1)
            tiles.append(img)
        th = max(t.shape[0] for t in tiles)
        tiles = [cv2.copyMakeBorder(t, 0, th - t.shape[0], 0, 0, cv2.BORDER_CONSTANT) for t in tiles]
        while len(tiles) % cols:
            tiles.append(np.zeros_like(tiles[0]))
        grid = np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)])
        cv2.imwrite(os.path.join(self.dir, "contact.jpg"), grid)

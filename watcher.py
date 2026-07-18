#!/usr/bin/env python3
"""
Second Brain — Local Pipeline Watcher (index-only, hardened)
Watches a directory tree and maintains brain_index.json:
  - nodes:    file index (graph nodes)
  - activity: per-day event counts by kind (feeds the 30-day timeline)
  - focus:    current work mode inferred from recent live file activity
Also appends human-readable events to brain_memory.md.

Deliberately does NOT include: any HTTP server, any network listener,
text-to-speech, screenshot capture, or a control endpoint. It only reads
files in the folder and writes brain_index.json + the memory changelog.

Install:  pip3 install watchdog
Run:      python3 watcher.py "<folder>"
Nightly:  python3 watcher.py "<folder>" --scan

To view the dashboard with this data, open dashboard.html through any static
server you trust and control, e.g.:  python3 -m http.server 8080
"""
import json, sys, time, hashlib
from datetime import datetime
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

WATCH_EXTENSIONS = {".md", ".txt", ".py", ".js", ".html", ".json", ".csv",
                    ".pdf", ".png", ".wav", ".mp3", ".log"}
IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".DS_Store"}
INDEX_FILE = "brain_index.json"
MEMORY_FILE = "brain_memory.md"
GENERATED = {INDEX_FILE, MEMORY_FILE, "recommendations.json", "control.json"}

FOCUS_KEYWORDS = {
    "lead": "sales", "client": "sales", "proposal": "sales",
    "invoice": "sales", "outreach": "sales", "pricing": "sales",
    "deploy": "deployment", "release": "deployment",
}
KIND_FOCUS = {"code": "deployment", "doc": "research",
              "voice_log": "capture", "screen_log": "capture"}
RECENT_WINDOW_SEC = 3600
RECENT_MAX = 100


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def file_id(path: Path) -> str:
    return "SRC-" + hashlib.sha1(str(path).encode()).hexdigest()[:8]


def classify_kind(path: Path) -> str:
    if path.suffix in {".wav", ".mp3"}:
        return "voice_log"
    if path.suffix in {".png", ".log"}:
        return "screen_log"
    if path.suffix in {".py", ".js", ".html"}:
        return "code"
    return "doc"


def classify_focus(path: Path, kind: str) -> str:
    p = str(path).lower()
    for kw, mode in FOCUS_KEYWORDS.items():
        if kw in p:
            return mode
    return KIND_FOCUS.get(kind, "general")


class BrainIndex:
    def __init__(self, root: Path):
        self.root = root
        self.index_path = root / INDEX_FILE
        self.memory_path = root / MEMORY_FILE
        self.data = {"nodes": {}, "activity": {}, "recent": [],
                     "focus": "general", "updated": None}
        if self.index_path.exists():
            self.data.update(json.loads(self.index_path.read_text()))

    def _record(self, path: Path, kind: str, event: str):
        day = self.data["activity"].setdefault(today(), {})
        day[kind] = day.get(kind, 0) + 1
        self.data["recent"].append(
            {"ts": time.time(), "focus": classify_focus(path, kind),
             "kind": kind, "event": event})
        self.data["recent"] = self.data["recent"][-RECENT_MAX:]
        self._update_focus()

    def _update_focus(self):
        cutoff = time.time() - RECENT_WINDOW_SEC
        votes = {}
        for e in self.data["recent"]:
            if e["ts"] >= cutoff and e.get("event") != "indexed":
                votes[e["focus"]] = votes.get(e["focus"], 0) + 1
        if votes:
            self.data["focus"] = max(votes, key=votes.get)

    def upsert(self, path: Path, event: str):
        rel = str(path.relative_to(self.root))
        fid = file_id(path)
        kind = classify_kind(path)
        self.data["nodes"][fid] = {
            "id": fid, "path": rel, "kind": kind, "event": event,
            "size": path.stat().st_size if path.exists() else 0,
            "modified": now(),
        }
        self._record(path, kind, event)
        self.save(f"{event.upper()}: `{rel}` ({kind}, {fid})")

    def remove(self, path: Path):
        fid = file_id(path)
        if self.data["nodes"].pop(fid, None):
            self.save(f"DELETED: `{path.name}` ({fid})")

    def save(self, log_line: str):
        self.data["updated"] = now()
        self.index_path.write_text(json.dumps(self.data, indent=2))
        if self.memory_path.exists():
            with self.memory_path.open("a") as f:
                f.write(f"- {now()} — {log_line}\n")
        print(f"[{now()}] focus={self.data['focus']} | {log_line}")

    def full_scan(self):
        for p in self.root.rglob("*"):
            if (p.is_file() and p.suffix in WATCH_EXTENSIONS
                    and not any(d in p.parts for d in IGNORE_DIRS)
                    and p.name not in GENERATED):
                self.upsert(p, "indexed")


class Handler(FileSystemEventHandler):
    DEBOUNCE_SEC = 5.0

    def __init__(self, index: BrainIndex):
        self.index = index
        self._last_event = {}

    def _debounced(self, path: str) -> bool:
        t = time.time()
        if t - self._last_event.get(path, 0) < self.DEBOUNCE_SEC:
            return True
        self._last_event[path] = t
        return False

    def _ok(self, path: str) -> bool:
        p = Path(path)
        return (p.suffix in WATCH_EXTENSIONS
                and not any(d in p.parts for d in IGNORE_DIRS)
                and p.name not in GENERATED)

    def on_created(self, e):
        if e.is_directory or self._debounced(e.src_path):
            return
        if self._ok(e.src_path):
            self.index.upsert(Path(e.src_path), "created")

    def on_modified(self, e):
        if e.is_directory or self._debounced(e.src_path):
            return
        if self._ok(e.src_path):
            self.index.upsert(Path(e.src_path), "modified")

    def on_deleted(self, e):
        if not e.is_directory and self._ok(e.src_path):
            self.index.remove(Path(e.src_path))


if __name__ == "__main__":
    args = sys.argv[1:]
    root = Path(args[0] if args and not args[0].startswith("--") else ".")
    root = root.expanduser().resolve()
    index = BrainIndex(root)

    if "--scan" in args:
        index.full_scan()
        sys.exit(0)

    observer = Observer()
    observer.schedule(Handler(index), str(root), recursive=True)
    observer.start()
    print(f"🧠 Watching {root} (index-only, no network) — Ctrl+C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

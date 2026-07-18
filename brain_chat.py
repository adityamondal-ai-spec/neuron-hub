#!/usr/bin/env python3
"""
brain_chat.py — Second Brain: one premium page (chat + memory + galaxy).

• Chat brain: local Ollama (offline, free) by default; Opus 4.8 (online, needs
  Anthropic API key) when you switch to it — auto-falls back to local offline.
• Obsidian memory: reads every .md note here as context; notes orbit the core.
• File peek + /find search over your notes.
• Battery-aware: animation drops to low, then fully static, as battery falls
  (or toggle it yourself) — light on a slow processor.
• Voice input button (Chrome, online) + Mac dictation (offline) in the box.
• Remembers the whole conversation to disk. No pip installs (stdlib only).

Run:  python3 brain_chat.py    →    open http://localhost:8090
Needs Ollama running:  ollama run llama3.2:3b
Optional background: save the galaxy image as bg.png (or bg.mp4) in this folder.
"""
import json
import os
import re
import ssl
import subprocess
import sys
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler


def _https_ctx():
    """SSL context that works even when macOS Python is missing system CA certs
    (uses certifi's bundle if available). Fixes CERTIFICATE_VERIFY_FAILED."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


_HTTPS = _https_ctx()

BASE      = Path(__file__).resolve().parent
VAULT     = BASE
MEM_FILE  = BASE / "brain_chat_memory.json"
CFG_FILE  = BASE / "brain_chat_config.json"
PORT      = 8090

OLLAMA_URL           = "http://localhost:11434/api/chat"
DEFAULT_LOCAL_MODEL  = "llama3.2:3b"
DEFAULT_VISION_MODEL = "moondream"          # offline screen vision (ollama pull moondream)
CLAUDE_URL          = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL        = "claude-opus-4-8"
CLAUDE_VERSION      = "2023-06-01"

MAX_TURNS       = 12
VAULT_CTX_CHARS = 1600
GENERATED = {"brain_index.json", "brain_memory.md", "recommendations.json",
             "control.json", MEM_FILE.name, CFG_FILE.name}
PERSONAL = {"PROFILE.md", "TASKS.md"}          # always included IN FULL in the prompt


def _read_personal(name: str) -> str:
    try:
        return (VAULT / name).read_text(encoding="utf-8", errors="replace")[:3000]
    except Exception:
        return ""


# ── config + memory ─────────────────────────────────────────────────────────
def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data) -> None:
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"[brain_chat] save error {path.name}: {e}")


KEYCHAIN_SERVICE = "anthropic_api_key"


def _keychain_get(service: str) -> str:
    """Same Keychain pattern as scripts/morning_run.sh — never store keys in files."""
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-a", os.environ.get("USER", ""),
             "-s", service, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def _keychain_set(service: str, value: str) -> bool:
    try:
        out = subprocess.run(
            ["security", "add-generic-password", "-a", os.environ.get("USER", ""),
             "-s", service, "-w", value, "-U"],
            capture_output=True, text=True, timeout=5,
        )
        return out.returncode == 0
    except Exception:
        return False


def load_cfg() -> dict:
    cfg = load_json(CFG_FILE, {})
    cfg.pop("anthropic_api_key", None)  # never read/kept from the file
    cfg["anthropic_api_key"] = _keychain_get(KEYCHAIN_SERVICE)
    cfg.setdefault("prefer", "local")
    cfg.setdefault("local_model", DEFAULT_LOCAL_MODEL)
    cfg.setdefault("vision_model", DEFAULT_VISION_MODEL)
    return cfg


def load_history() -> list:
    return load_json(MEM_FILE, [])


# ── vault / notes ───────────────────────────────────────────────────────────
def _note_title(text: str, stem: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            return s.lstrip("#").strip() or stem
    return stem


def vault_context() -> str:
    notes = []
    for md in sorted(VAULT.glob("*.md")):
        if md.name in GENERATED or md.name in PERSONAL:
            continue
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        body = " ".join(text.split())
        notes.append(f"- {_note_title(text, md.stem)}: {body[:180]}")
    if not notes:
        return ""
    return ("Notes from the user's Obsidian vault (use as memory/context):\n"
            + "\n".join(notes))[:VAULT_CTX_CHARS]


def system_prompt() -> str:
    base = ("You are HAMI, the user's personal AI and Second Brain. "
            "Talk like a sharp, warm friend — natural and human, NOT a corporate assistant. "
            "Be concise and real, with personality and warmth. No stiff filler "
            "('I'd be happy to assist', 'How else may I help'). The user often writes "
            "Hinglish — match that casual mix. "
            "Be PROACTIVE: you know who they are (ABOUT ME), you track their pending work "
            "(MY TASKS), and you push them toward their goals. When they ask what to do, "
            "prioritise from their tasks + goals and give ONE clear next action. "
            "If you don't know something, say so plainly. "
            "You can ONLY do actions the action layer executed (opening YouTube/a site/a "
            "search — nothing else). If the user asks for anything you cannot actually "
            "perform, say honestly 'yeh main abhi nahi kar sakta' — NEVER claim or roleplay "
            "that you performed an action you didn't.")
    parts = [base]
    prof = _read_personal("PROFILE.md")
    if prof:
        parts.append("[ABOUT ME — who the user is + their goals]\n" + prof)
    tasks = _read_personal("TASKS.md")
    if tasks:
        parts.append("[MY TASKS — the user's pending work; track it, remind, and push]\n" + tasks)
    ctx = vault_context()
    if ctx:
        parts.append(ctx)
    return "\n\n".join(parts)


def notes_list() -> list:
    out = []
    for md in sorted(VAULT.glob("*.md")):
        if md.name in GENERATED:
            continue
        try:
            head = md.read_text(encoding="utf-8", errors="replace")[:400]
        except Exception:
            head = ""
        out.append({"name": md.name, "title": _note_title(head, md.stem)})
    return out


def note_content(name: str) -> dict | None:
    p = VAULT / Path(name).name
    if p.suffix.lower() != ".md" or not p.exists():
        return None
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    return {"name": p.name, "title": _note_title(text, p.stem), "content": text[:6000]}


# ── model backends ──────────────────────────────────────────────────────────
def call_ollama(model: str, system: str, messages: list) -> str:
    payload = {"model": model,
               "messages": [{"role": "system", "content": system}] + messages,
               "stream": False}
    req = urllib.request.Request(OLLAMA_URL, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode("utf-8"))
    return (data.get("message", {}) or {}).get("content", "").strip()


def call_claude(api_key: str, system: str, messages: list) -> str:
    payload = {"model": CLAUDE_MODEL, "max_tokens": 1024, "system": system, "messages": messages}
    req = urllib.request.Request(CLAUDE_URL, data=json.dumps(payload).encode("utf-8"),
                                 headers={"content-type": "application/json",
                                          "x-api-key": api_key,
                                          "anthropic-version": CLAUDE_VERSION}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode("utf-8"))
    return "".join(p.get("text", "") for p in data.get("content", [])
                   if p.get("type") == "text").strip()


def generate(system: str, messages: list, cfg: dict) -> tuple[str, str]:
    if cfg.get("prefer") == "opus" and cfg.get("anthropic_api_key"):
        try:
            reply = call_claude(cfg["anthropic_api_key"], system, messages)
            if reply:
                return reply, "Opus 4.8 (online)"
        except Exception as e:
            print(f"[brain_chat] Opus unavailable ({e}) — falling back to local.")
    try:
        reply = call_ollama(cfg.get("local_model", DEFAULT_LOCAL_MODEL), system, messages)
        return (reply or "(empty reply)"), f"{cfg.get('local_model', DEFAULT_LOCAL_MODEL)} (offline)"
    except Exception as e:
        return (f"⚠️ Local model unreachable. Start Ollama:  ollama run {DEFAULT_LOCAL_MODEL}\n\n({e})",
                "error")


def respond(user_msg: str) -> dict:
    cfg = load_cfg()
    history = load_history()
    history.append({"role": "user", "content": user_msg})
    reply, provider = generate(system_prompt(), history[-MAX_TURNS:], cfg)
    history.append({"role": "assistant", "content": reply})
    save_json(MEM_FILE, history)
    return {"reply": reply, "provider": provider}


# ── HAMI agent (Opus 4.8 brain + terminal + browser) ────────────────────────
import subprocess as _sub

AGENT_TOOLS = [
    {"name": "run_terminal",
     "description": "Run a shell command on the user's Mac (working dir = home) and return its "
                    "output. Use for git clone, downloads, pip/npm installs, file operations, "
                    "running scripts. NEVER run destructive commands.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}},
                      "required": ["command"]}},
    {"name": "open_url",
     "description": "Open a URL in the user's default browser.",
     "input_schema": {"type": "object", "properties": {"url": {"type": "string"}},
                      "required": ["url"]}},
    {"name": "remember",
     "description": "Save a durable fact about the user to HAMI's memory.",
     "input_schema": {"type": "object", "properties": {"key": {"type": "string"},
                      "value": {"type": "string"}}, "required": ["key", "value"]}},
]

_DANGER = ["rm -rf /", "rm -rf ~", "rm -rf *", "mkfs", "dd if=", ":(){", "> /dev/",
           "sudo rm", "diskutil erase", "shutdown", "reboot", "chmod -r 000", "killall"]


def _run_terminal(command: str) -> str:
    if any(d in command.lower() for d in _DANGER):
        return "⛔ Blocked — that command looks destructive. If you're sure, run it yourself."
    try:
        r = _sub.run(command, shell=True, capture_output=True, text=True,
                     timeout=90, cwd=str(Path.home()))
        out = (r.stdout or "") + (("\n[stderr] " + r.stderr) if r.stderr else "")
        return (out.strip() or "(done, no output)")[:3000]
    except Exception as e:
        return f"error: {e}"


def _open_url(url: str) -> str:
    try:
        if sys.platform == "darwin":
            _sub.Popen(["open", url])
        else:
            import webbrowser
            webbrowser.open(url)
        return f"Opened {url}"
    except Exception as e:
        return f"error: {e}"


def _agent_tool(name: str, inp: dict) -> str:
    if name == "run_terminal":
        return _run_terminal(inp.get("command", ""))
    if name == "open_url":
        return _open_url(inp.get("url", ""))
    if name == "remember":
        try:
            with (VAULT / "HAMI Memory.md").open("a", encoding="utf-8") as fh:
                fh.write(f"- {inp.get('key','')}: {inp.get('value','')}\n")
            return "saved to memory"
        except Exception as e:
            return f"error: {e}"
    return f"unknown tool: {name}"


def _call_claude_agent(system: str, messages: list, key: str) -> dict:
    payload = {"model": CLAUDE_MODEL, "max_tokens": 2048, "system": system,
               "tools": AGENT_TOOLS, "messages": messages}
    req = urllib.request.Request(CLAUDE_URL, data=json.dumps(payload).encode("utf-8"),
                                 headers={"content-type": "application/json",
                                          "x-api-key": key,
                                          "anthropic-version": CLAUDE_VERSION}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def agent_respond(user_msg: str) -> dict:
    """Opus 4.8 agent loop: plans + actually uses terminal/browser tools."""
    cfg = load_cfg()
    key = cfg.get("anthropic_api_key")
    hist = load_history()
    messages = [{"role": m["role"], "content": m["content"]} for m in hist[-MAX_TURNS:]]
    messages.append({"role": "user", "content": user_msg})
    system = (system_prompt() + "\n\nYou are an ACTING agent: you can run terminal commands "
              "(run_terminal) and open the browser (open_url). Actually DO the task with your "
              "tools — don't just describe it. Chain steps, read the output, and finish. "
              "Be careful; never run destructive commands.")
    final = ""
    for _ in range(8):
        try:
            resp = _call_claude_agent(system, messages, key)
        except Exception as e:
            return {"reply": f"⚠️ Opus error: {e}", "provider": "error"}
        if resp.get("type") == "error":
            return {"reply": "⚠️ " + str(resp.get("error", {}).get("message", resp)), "provider": "error"}
        content = resp.get("content", [])
        t = "".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
        if t:
            final = t
        messages.append({"role": "assistant", "content": content})
        tus = [b for b in content if b.get("type") == "tool_use"]
        if resp.get("stop_reason") != "tool_use" or not tus:
            break
        messages.append({"role": "user", "content":
                         [{"type": "tool_result", "tool_use_id": tu["id"],
                           "content": _agent_tool(tu["name"], tu.get("input", {}))} for tu in tus]})
    hist.append({"role": "user", "content": user_msg})
    hist.append({"role": "assistant", "content": final or "(done)"})
    save_json(MEM_FILE, hist)
    return {"reply": final or "(done)", "provider": "HAMI · Opus agent 🛠️"}


# ── screen vision (Watch me) ────────────────────────────────────────────────
def call_ollama_vision(model: str, prompt: str, image_b64: str) -> str:
    payload = {"model": model, "stream": False,
               "messages": [{"role": "user",
                             "content": prompt or "Briefly describe what is on this screen.",
                             "images": [image_b64]}]}
    req = urllib.request.Request(OLLAMA_URL, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.loads(r.read().decode("utf-8"))
    return (data.get("message", {}) or {}).get("content", "").strip()


def call_claude_vision(api_key: str, prompt: str, image_b64: str) -> str:
    payload = {"model": CLAUDE_MODEL, "max_tokens": 1024,
               "messages": [{"role": "user", "content": [
                   {"type": "image", "source": {"type": "base64",
                    "media_type": "image/jpeg", "data": image_b64}},
                   {"type": "text", "text": prompt or "Briefly describe what is on this screen."}]}]}
    req = urllib.request.Request(CLAUDE_URL, data=json.dumps(payload).encode("utf-8"),
                                 headers={"content-type": "application/json",
                                          "x-api-key": api_key,
                                          "anthropic-version": CLAUDE_VERSION}, method="POST")
    with urllib.request.urlopen(req, timeout=90) as r:
        data = json.loads(r.read().decode("utf-8"))
    return "".join(p.get("text", "") for p in data.get("content", [])
                   if p.get("type") == "text").strip()


def vision_respond(prompt: str, image_b64: str) -> dict:
    cfg = load_cfg()
    if cfg.get("prefer") == "opus" and cfg.get("anthropic_api_key"):
        try:
            reply = call_claude_vision(cfg["anthropic_api_key"], prompt, image_b64)
            if reply:
                return {"reply": reply, "provider": "Opus 4.8 vision (online)"}
        except Exception as e:
            print(f"[vision] Opus vision unavailable ({e}) — falling back to local.")
    vm = cfg.get("vision_model", DEFAULT_VISION_MODEL)
    try:
        reply = call_ollama_vision(vm, prompt, image_b64)
        return {"reply": reply or "(no description)", "provider": f"{vm} vision (offline)"}
    except Exception as e:
        return {"reply": f"⚠️ Vision model unreachable. For offline screen vision run once:  "
                          f"ollama pull {DEFAULT_VISION_MODEL}\n\n({e})", "provider": "error"}


PAGE = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Second Brain</title>
<style>
  :root{--mag:#e838d6;--cyan:#38e6ff;--text:#eaf0ff;--muted:#8390b8;--border:rgba(120,140,220,.20)}
  *{box-sizing:border-box;margin:0}
  html,body{height:100%}
  body{color:var(--text);font:15px/1.55 -apple-system,'Segoe UI',Roboto,sans-serif;overflow:hidden;
    background:
      linear-gradient(rgba(4,5,12,.5),rgba(4,5,12,.74)),
      url('/bg.png') center/cover no-repeat fixed,
      radial-gradient(ellipse at 80% 20%,rgba(60,30,90,.5),transparent 55%),
      radial-gradient(ellipse at 18% 82%,rgba(20,50,110,.45),transparent 55%),
      #050510}
  #bgvid{position:fixed;inset:0;width:100%;height:100%;object-fit:cover;z-index:0}
  .bgdim{position:fixed;inset:0;z-index:0;pointer-events:none;background:linear-gradient(rgba(4,5,12,.5),rgba(4,5,12,.72))}
  #space{position:fixed;inset:0;z-index:1}
  #orbit{position:fixed;inset:0;z-index:2;pointer-events:none;overflow:hidden}
  .chip{position:absolute;transform:translate(-50%,-50%);pointer-events:auto;cursor:pointer;
    font-size:11px;letter-spacing:.3px;color:#cfe0ff;background:rgba(14,18,38,.72);
    border:1px solid rgba(56,230,255,.28);border-radius:99px;padding:5px 11px;white-space:nowrap;
    max-width:180px;overflow:hidden;text-overflow:ellipsis;transition:color .15s,border-color .15s}
  .chip:hover{color:#fff;border-color:var(--mag);box-shadow:0 0 14px rgba(232,56,214,.4)}
  .app{position:relative;z-index:3;height:100vh;display:flex;flex-direction:column}
  header{display:flex;align-items:center;gap:9px;padding:11px 16px;
    background:linear-gradient(180deg,rgba(9,11,24,.6),transparent);backdrop-filter:blur(8px)}
  .logo{font-weight:800;letter-spacing:3px;font-size:13px;text-shadow:0 0 16px rgba(232,56,214,.6)}
  .logo em{color:var(--mag);font-style:normal}
  .badge{font-size:11px;color:var(--cyan);border:1px solid rgba(56,230,255,.4);border-radius:99px;
    padding:3px 10px;background:rgba(56,230,255,.07);cursor:pointer;user-select:none}
  .badge.mode{margin-left:auto}
  .gear{background:rgba(20,24,44,.5);border:1px solid var(--border);color:var(--muted);border-radius:9px;cursor:pointer;padding:5px 9px}
  .gear:hover{color:var(--mag);border-color:var(--mag)}
  main{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:11px;max-width:800px;width:100%;margin:0 auto}
  main::-webkit-scrollbar{width:3px}main::-webkit-scrollbar-thumb{background:rgba(120,140,220,.3);border-radius:4px}
  .welcome{margin:auto;text-align:center;color:var(--muted);max-width:420px}
  .welcome .core{width:64px;height:64px;margin:0 auto 14px;border-radius:50%;
    background:radial-gradient(circle at 40% 38%,#fff,#38e6ff 42%,#a828c8 78%,transparent);
    box-shadow:0 0 38px rgba(56,230,255,.5),0 0 70px rgba(232,56,214,.3);animation:pulse 4s ease-in-out infinite}
  @keyframes pulse{50%{transform:scale(1.07)}}
  .welcome h2{color:var(--text);font-size:17px;letter-spacing:1px;margin-bottom:6px}
  .msg{max-width:86%;padding:10px 14px;border-radius:15px;white-space:pre-wrap;word-wrap:break-word}
  .u{align-self:flex-end;background:linear-gradient(135deg,rgba(232,56,214,.2),rgba(168,40,200,.1));
    border:1px solid rgba(232,56,214,.42);border-bottom-right-radius:5px}
  .a{align-self:flex-start;background:linear-gradient(135deg,rgba(15,20,42,.82),rgba(11,15,32,.62));
    border:1px solid rgba(56,230,255,.28);border-bottom-left-radius:5px}
  .who{font-size:9px;color:var(--muted);letter-spacing:1.5px;text-transform:uppercase;margin-bottom:3px}
  .a .who{color:var(--cyan)}.u .who{color:var(--mag)}
  footer{padding:11px 16px;background:linear-gradient(0deg,rgba(9,11,24,.72),transparent);backdrop-filter:blur(8px)}
  .row{max-width:800px;margin:0 auto;display:flex;gap:8px;align-items:flex-end}
  .mic{width:44px;height:44px;flex:none;border-radius:12px;border:1px solid rgba(56,230,255,.4);
    background:rgba(20,24,44,.55);color:var(--cyan);font-size:17px;cursor:pointer}
  .mic.rec{color:#fff;border-color:#ff4d6d;background:rgba(255,77,109,.2);box-shadow:0 0 20px rgba(255,77,109,.5);animation:rec 1.1s infinite}
  @keyframes rec{50%{box-shadow:0 0 30px rgba(255,77,109,.85)}}
  textarea{flex:1;background:rgba(8,10,22,.72);border:1px solid var(--border);border-radius:12px;color:var(--text);padding:12px;font:inherit;resize:none;max-height:130px}
  textarea:focus{outline:none;border-color:var(--cyan);box-shadow:0 0 15px rgba(56,230,255,.22)}
  .send{background:linear-gradient(135deg,var(--mag),#a828c8);color:#fff;border:none;border-radius:12px;padding:0 18px;height:44px;font-weight:800;cursor:pointer;box-shadow:0 0 20px rgba(232,56,214,.35)}
  .hint{max-width:800px;margin:6px auto 0;font-size:10.5px;color:var(--muted)}
  #peek{position:fixed;top:0;right:-380px;width:min(360px,90vw);height:100vh;z-index:15;
    background:linear-gradient(180deg,rgba(12,15,32,.97),rgba(8,10,24,.97));border-left:1px solid rgba(56,230,255,.28);
    padding:18px;overflow-y:auto;transition:right .25s;box-shadow:-10px 0 40px rgba(0,0,0,.5)}
  #peek.on{right:0}
  #peek h3{font-size:14px;color:var(--cyan);margin-bottom:4px}
  #peek .body{white-space:pre-wrap;font-size:13px;color:#d3ddf5;margin-top:10px}
  #peek .x{position:absolute;top:12px;right:14px;cursor:pointer;color:var(--muted)}
  #peek .ask{margin-top:14px;background:linear-gradient(135deg,var(--mag),#a828c8);color:#fff;border:none;border-radius:9px;padding:8px 14px;cursor:pointer;font-weight:700}
  #toast{position:fixed;left:50%;bottom:88px;transform:translateX(-50%);z-index:30;background:rgba(16,20,40,.96);
    border:1px solid var(--border);border-radius:10px;padding:9px 15px;font-size:12px;opacity:0;transition:.3s;pointer-events:none;max-width:80vw;text-align:center}
  #toast.on{opacity:1}
  .overlay{position:fixed;inset:0;z-index:40;background:rgba(2,3,10,.72);display:none;align-items:center;justify-content:center;backdrop-filter:blur(5px)}
  .overlay.on{display:flex}
  .modal{background:linear-gradient(160deg,rgba(16,20,40,.97),rgba(10,12,28,.97));border:1px solid rgba(56,230,255,.3);border-radius:16px;padding:22px;width:min(460px,92vw);display:flex;flex-direction:column;gap:10px}
  .modal h3{font-size:13px;letter-spacing:2px;color:var(--cyan)}
  .modal label{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:1px}
  .modal input,.modal select{background:rgba(8,10,22,.9);border:1px solid var(--border);border-radius:9px;padding:10px 12px;color:var(--text);font:inherit}
  .modal .acts{display:flex;justify-content:space-between;gap:8px;margin-top:6px}
  .modal button{border:1px solid var(--border);background:rgba(20,24,44,.7);color:var(--text);border-radius:9px;padding:9px 15px;cursor:pointer}
  .modal button.save{background:linear-gradient(135deg,var(--mag),#a828c8);color:#fff;border:none;font-weight:800}
  .st{font-size:11px;color:var(--muted);min-height:14px}.note{font-size:11px;color:var(--muted);line-height:1.5}
</style></head><body>
<video id="bgvid" autoplay muted loop playsinline poster="/bg.png"><source src="/bg.mp4" type="video/mp4"></video>
<video id="scrv" muted playsinline style="display:none"></video>
<canvas id="scrc" style="display:none"></canvas>
<div class="bgdim"></div>
<canvas id="space"></canvas>
<div id="orbit"></div>
<div class="app">
  <header>
    <div class="logo"><em>◉</em> SECOND&nbsp;BRAIN</div>
    <div class="badge mode" id="mode">offline</div>
    <div class="badge" id="perf" onclick="cyclePerf()" title="Animation / battery mode">⚡</div>
    <button class="gear" onclick="openCfg()">⚙</button>
    <button class="gear" onclick="resetChat()" title="New chat">🗑</button>
  </header>
  <main id="feed"></main>
  <footer>
    <div class="row">
      <button class="mic" id="mic" onclick="toggleVoice()" title="Voice">🎤</button>
      <button class="mic" id="watch" onclick="toggleWatch()" title="Watch my screen (on/off)">👁</button>
      <textarea id="inp" rows="1" placeholder="Ask, /find a note, or 👁 watch screen…"></textarea>
      <button class="send" onclick="send()">➤</button>
    </div>
    <div class="hint">🎤 voice · 👁 watch = turn on, ask about your screen, turn off · /find &lt;word&gt; searches notes · tap a floating note to open</div>
  </footer>
</div>
<div id="peek"><span class="x" onclick="closePeek()">✕</span><h3 id="pk-t"></h3><div class="body" id="pk-b"></div><button class="ask" id="pk-ask">Ask brain about this</button></div>
<div id="toast"></div>

<div class="overlay" id="cfg" onclick="if(event.target===this)closeCfg()">
  <div class="modal">
    <h3>⚙ SETTINGS</h3>
    <label>Mode</label>
    <select id="prefer">
      <option value="local">Offline — local model (free, private)</option>
      <option value="opus">Online — Opus 4.8 (needs API key; falls back offline)</option>
    </select>
    <label>Anthropic API key (Opus 4.8 · online only)</label>
    <input id="key" type="password" placeholder="API key… (blank = keep)" autocomplete="off">
    <label>Local model name</label>
    <input id="model" placeholder="llama3.2:3b" autocomplete="off">
    <div class="note">Opus 4.8 can't run offline — needs internet + a paid Anthropic API key (separate from Claude Plus). Offline or without a key, the app uses your local model.</div>
    <div class="st" id="cfgst"></div>
    <div class="acts"><button onclick="closeCfg()">Cancel</button><button class="save" onclick="saveCfg()">Save</button></div>
  </div>
</div>

<script>
/* ===== performance / battery manager ===== */
let PERF='high', PERF_FORCE=null;          // high | low | off ; force overrides battery
const perfBadge=document.getElementById('perf');
const bgvid=document.getElementById('bgvid');
if(bgvid) bgvid.addEventListener('error',()=>{bgvid.style.display='none';});
function applyVideoPerf(){ if(!bgvid) return;
  if(PERF==='high'){ const pr=bgvid.play?bgvid.play():null; if(pr&&pr.catch)pr.catch(()=>{}); }
  else if(bgvid.pause){ bgvid.pause(); } }
function setPerf(p){PERF=p; perfBadge.textContent=p==='high'?'⚡':p==='low'?'🔋':'⏸';
  perfBadge.title='Animation: '+p+(PERF_FORCE?' (locked)':' (auto/battery)'); applyVideoPerf();}
function cyclePerf(){const o=['high','low','off']; PERF_FORCE=o[(o.indexOf(PERF_FORCE||PERF)+1)%3]; setPerf(PERF_FORCE); sizeCanvas();}
async function initBattery(){
  if(window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches){PERF_FORCE='low';}
  try{
    const b=await navigator.getBattery();
    const apply=()=>{ if(PERF_FORCE) return;
      setPerf(b.charging?'high':(b.level<0.15?'off':(b.level<0.30?'low':'high'))); sizeCanvas(); };
    b.addEventListener('levelchange',apply); b.addEventListener('chargingchange',apply); apply();
  }catch(e){ if(!PERF_FORCE) setPerf('high'); }
}
document.addEventListener('visibilitychange',()=>{ if(document.hidden) running=false; else {running=true; draw();} });

/* ===== galaxy constellation (perf-aware) ===== */
const cv=document.getElementById('space'), cx=cv.getContext('2d');
let W,H,pts,stars,running=true; const mouse={x:-999,y:-999};
function nodeCount(){return PERF==='off'?0:PERF==='low'?18:Math.min(46,Math.round(innerWidth*innerHeight/30000));}
function sizeCanvas(){
  W=cv.width=innerWidth;H=cv.height=innerHeight;const n=nodeCount();
  pts=Array.from({length:n},()=>({x:Math.random()*W,y:Math.random()*H,vx:(Math.random()-.5)*.25,vy:(Math.random()-.5)*.25,r:Math.random()*1.7+.6}));
  const sn=PERF==='off'?60:PERF==='low'?90:Math.min(180,Math.round(W*H/11000));
  stars=Array.from({length:sn},()=>({x:Math.random()*W,y:Math.random()*H,r:Math.random()*1.1+.2,p:Math.random()*6.28}));
  layoutOrbit();
}
addEventListener('resize',sizeCanvas);
addEventListener('mousemove',e=>{mouse.x=e.clientX;mouse.y=e.clientY;});
let T=0,lastFrame=0;
function draw(ts){
  if(!running) return;
  requestAnimationFrame(draw);
  ts=ts||0; if(ts-lastFrame<32) return; lastFrame=ts;   // ~30fps cap (smoother, lighter)
  T+=0.032; cx.clearRect(0,0,W,H);
  for(const s of stars){const a=.3+.45*Math.sin(T*1.3+s.p);cx.globalAlpha=Math.max(0,a);cx.fillStyle='#cfe0ff';cx.beginPath();cx.arc(s.x,s.y,s.r,0,7);cx.fill();}
  cx.globalAlpha=1;
  if(PERF!=='off'){
    for(let i=0;i<pts.length;i++){const a=pts[i];a.x+=a.vx;a.y+=a.vy;
      if(a.x<0||a.x>W)a.vx*=-1;if(a.y<0||a.y>H)a.vy*=-1;
      for(let j=i+1;j<pts.length;j++){const b=pts[j],dx=a.x-b.x,dy=a.y-b.y,d=dx*dx+dy*dy;
        if(d<19000){const o=(1-d/19000)*.45;cx.strokeStyle='rgba(120,190,255,'+o.toFixed(3)+')';cx.lineWidth=.7;cx.beginPath();cx.moveTo(a.x,a.y);cx.lineTo(b.x,b.y);cx.stroke();}}
      if(PERF==='high'){const mx=a.x-mouse.x,my=a.y-mouse.y,md=mx*mx+my*my;
        if(md<32000){const o=(1-md/32000)*.8;cx.strokeStyle='rgba(232,56,214,'+o.toFixed(3)+')';cx.lineWidth=1;cx.beginPath();cx.moveTo(a.x,a.y);cx.lineTo(mouse.x,mouse.y);cx.stroke();}}
    }
    cx.fillStyle='rgba(210,230,255,.95)';                 // no shadowBlur → big smoothness win
    for(const p of pts){cx.beginPath();cx.arc(p.x,p.y,p.r,0,7);cx.fill();}
  }
  orbitStep();
}

/* ===== orbiting memory nodes ===== */
const orbitEl=document.getElementById('orbit'); let chips=[], notes=[];
async function loadNotes(){
  try{ notes=(await (await fetch('/notes')).json()).notes||[]; }catch(e){ notes=[]; }
  orbitEl.innerHTML=''; chips=[];
  notes.slice(0,10).forEach((n,i)=>{
    const c=document.createElement('div'); c.className='chip'; c.textContent=n.title;
    c.onclick=()=>openNote(n.name);
    orbitEl.appendChild(c);
    chips.push({el:c, ang:(i/Math.min(notes.length,10))*6.283, rad:0, spd:0.12+Math.random()*0.06});
  });
  layoutOrbit();
}
function layoutOrbit(){const R=Math.min(innerWidth,innerHeight)*0.36; chips.forEach(c=>c.rad=R*(0.7+Math.random()*0.45));}
function orbitStep(){
  const cxp=innerWidth/2, cyp=innerHeight*0.46, sp=PERF==='off'?0:PERF==='low'?0.15:0.5;
  for(const c of chips){ c.ang+=0.0016*c.spd*sp*60;
    const x=cxp+Math.cos(c.ang)*c.rad, y=cyp+Math.sin(c.ang)*c.rad*0.62;
    c.el.style.left=x+'px'; c.el.style.top=y+'px'; }
}

/* ===== file peek ===== */
async function openNote(name){
  try{ const n=await (await fetch('/note?name='+encodeURIComponent(name))).json();
    if(n.error){toast('Note nahi mila');return;}
    document.getElementById('pk-t').textContent=n.title;
    document.getElementById('pk-b').textContent=n.content;
    document.getElementById('pk-ask').onclick=()=>{closePeek(); inp.value='Summarize the note "'+n.title+'".'; send();};
    document.getElementById('peek').classList.add('on');
  }catch(e){toast('Open nahi hua');}
}
function closePeek(){document.getElementById('peek').classList.remove('on');}

/* ===== toast ===== */
let _tt; const toastEl=document.getElementById('toast');
function toast(m){toastEl.textContent=m;toastEl.classList.add('on');clearTimeout(_tt);_tt=setTimeout(()=>toastEl.classList.remove('on'),3000);}

/* ===== chat ===== */
const feed=document.getElementById('feed'), inp=document.getElementById('inp'), mode=document.getElementById('mode');
const WELCOME='<div class="welcome"><div class="core"></div><h2>Second Brain</h2><div>Ask anything · /find a note · tap a floating note. Offline, remembers everything.</div></div>';
function showWelcome(){ if(!feed.children.length) feed.innerHTML=WELCOME; }
function clearWelcome(){ const w=feed.querySelector('.welcome'); if(w) w.remove(); }
function add(role,text,who){clearWelcome();
  const d=document.createElement('div');d.className='msg '+(role==='user'?'u':'a');
  d.innerHTML='<div class="who">'+(who||(role==='user'?'you':'brain'))+'</div>';
  const b=document.createElement('div');b.textContent=text;d.appendChild(b);
  feed.appendChild(d);feed.scrollTop=feed.scrollHeight;}
inp.addEventListener('input',()=>{inp.style.height='auto';inp.style.height=Math.min(inp.scrollHeight,130)+'px';});
inp.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();}});
function localFind(q){
  const hits=notes.filter(n=>n.title.toLowerCase().includes(q.toLowerCase()));
  add('user','/find '+q);
  if(!hits.length){add('assistant','Koi note nahi mila for "'+q+'".','brain');return;}
  const box=document.createElement('div');box.className='msg a';box.innerHTML='<div class="who">brain</div>';
  const b=document.createElement('div');b.textContent=hits.length+' note(s): ';
  hits.slice(0,8).forEach(n=>{const s=document.createElement('span');s.textContent='📄 '+n.title+'  ';s.style.cssText='color:#38e6ff;cursor:pointer';s.onclick=()=>openNote(n.name);b.appendChild(s);});
  box.appendChild(b);clearWelcome();feed.appendChild(box);feed.scrollTop=feed.scrollHeight;
}
async function send(){
  const t=inp.value.trim(); if(!t) return; inp.value=''; inp.style.height='auto';
  if(t.toLowerCase().startsWith('/find ')){ localFind(t.slice(6).trim()); return; }
  add('user',t);
  const wait=document.createElement('div');wait.className='msg a';wait.innerHTML='<div class="who">brain</div>';
  const wb=document.createElement('div');wb.textContent=watching?'👁 looking…':'…';wait.appendChild(wb);feed.appendChild(wait);feed.scrollTop=feed.scrollHeight;
  try{
    let j;
    if(watching){ const img=grabFrame();
      j=await (await fetch('/vision',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:t,image:img})})).json();
    } else {
      j=await (await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:t})})).json();
    }
    wait.querySelector('.who').textContent=j.provider||'brain';wb.textContent=j.reply;
    if(j.provider)mode.textContent=j.provider;
  }catch(e){wb.textContent='⚠️ '+e;}
}

/* ===== voice ===== */
let rec=null,listening=false; const micBtn=document.getElementById('mic');
function toggleVoice(){
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SR){toast('Is browser mein in-app voice nahi. Box mein Mac dictation (fn fn) use karo — offline.');inp.focus();return;}
  if(listening){rec.stop();return;}
  rec=new SR();rec.lang='en-IN';rec.interimResults=true;rec.continuous=false;const base=inp.value;
  rec.onstart=()=>{listening=true;micBtn.classList.add('rec');};
  rec.onerror=e=>{listening=false;micBtn.classList.remove('rec');
    if(e.error==='network')toast('In-app voice ke liye internet chahiye. Offline: Mac dictation (fn fn).');
    else if(e.error==='not-allowed')toast('Mic permission do browser ko.');};
  rec.onend=()=>{listening=false;micBtn.classList.remove('rec');};
  rec.onresult=e=>{let t='';for(const r of e.results)t+=r[0].transcript;inp.value=(base?base+' ':'')+t;inp.dispatchEvent(new Event('input'));};
  rec.start();
}

/* ===== watch me (manual on/off screen vision) ===== */
let screenStream=null,watching=false; const watchBtn=document.getElementById('watch');
async function toggleWatch(){
  if(watching){ stopWatch(); toast('👁 Watch off'); return; }
  try{ screenStream=await navigator.mediaDevices.getDisplayMedia({video:{frameRate:1}}); }
  catch(e){ toast('Screen share cancel ho gaya'); return; }
  const v=document.getElementById('scrv'); v.srcObject=screenStream; try{await v.play();}catch(e){}
  watching=true; watchBtn.classList.add('rec');
  toast('👁 Watch ON — ab jo poochoge screen ke saath jayega. Off karne ko dobara 👁 tap karo.');
  screenStream.getVideoTracks()[0].onended=()=>stopWatch();
}
function stopWatch(){ watching=false; watchBtn.classList.remove('rec');
  if(screenStream){ screenStream.getTracks().forEach(t=>t.stop()); screenStream=null; } }
function grabFrame(){
  const v=document.getElementById('scrv'), c=document.getElementById('scrc');
  const sw=v.videoWidth||1280, sh=v.videoHeight||720, w=Math.min(1280,sw), h=Math.round(sh*(w/sw));
  c.width=w; c.height=h; c.getContext('2d').drawImage(v,0,0,w,h);
  return c.toDataURL('image/jpeg',0.7).split(',')[1];
}

/* ===== settings / history ===== */
async function loadHistory(){try{const j=await (await fetch('/history')).json();feed.innerHTML='';(j.history||[]).forEach(m=>add(m.role,m.content,m.role==='user'?'you':'brain'));}catch(e){}showWelcome();}
async function initMode(){try{const c=await (await fetch('/config')).json();
  if(c.prefer==='opus') mode.textContent=c.has_key?'Opus 4.8 (online)':'Opus — add key in ⚙';
  else mode.textContent=(c.local_model||'local')+' (offline)';}catch(e){}}
function openCfg(){document.getElementById('cfgst').textContent='';fetch('/config').then(r=>r.json()).then(c=>{document.getElementById('prefer').value=c.prefer||'local';document.getElementById('model').value=c.local_model||'llama3.2:3b';document.getElementById('key').placeholder=c.has_key?'•••••• saved — blank = same rahegi':'API key… (blank = keep)';});document.getElementById('cfg').classList.add('on');}
function closeCfg(){document.getElementById('cfg').classList.remove('on');}
async function saveCfg(){const body={prefer:document.getElementById('prefer').value,local_model:document.getElementById('model').value.trim()};const k=document.getElementById('key').value.trim();if(k)body.anthropic_api_key=k;
  document.getElementById('cfgst').textContent='Saving…';await fetch('/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  document.getElementById('cfgst').textContent='Saved.';mode.textContent=(body.prefer==='opus')?'Opus 4.8 (online)':'offline';setTimeout(closeCfg,700);}
async function resetChat(){if(!confirm('Fresh chat? (notes stay, conversation clears)'))return;await fetch('/reset',{method:'POST'});feed.innerHTML='';showWelcome();}

/* ===== boot ===== */
initBattery(); sizeCanvas(); loadNotes(); loadHistory(); initMode(); draw();
</script></body></html>"""


# ── action layer: whitelisted intents only, no arbitrary shell ──────────────
BRAIN_MEMORY_MD = BASE / "brain_memory.md"

# domain-only, e.g. "github.com" or "docs.github.com/foo" — rejects spaces,
# shell metacharacters, "javascript:", "file:", or anything else not shaped
# like a plain hostname(+path).
_DOMAIN_RE = re.compile(
    r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}"
    r"(/[a-zA-Z0-9._~\-/%]*)?$", re.I)

PLAY_RE   = re.compile(r"^(?:play|youtube|chalao|lagao)\b[:\-]?\s+(.+)$", re.I)
OPEN_RE   = re.compile(r"^(?:open|kholo)\b[:\-]?\s+(\S+)$", re.I)
SEARCH_RE = re.compile(r"^(?:search|dhundo)\b[:\-]?\s+(.+)$", re.I)

# Action-shaped requests we deliberately do NOT support. Matched and refused
# HERE, deterministically — never handed to the LLM, because a small local
# model (qwen2.5:3b) does not reliably follow the honesty instruction in the
# system prompt and can say "Sure thing!" to something it can't actually do.
UNSUPPORTED_RE = re.compile(
    r"^(?:send|email|mail|message|whatsapp|dm|call|phone|ring|post|tweet|"
    r"book|order|buy|pay|transfer|delete|remove|reply|bhejo|bhej do|"
    r"karo call|call karo)\b", re.I)
HONEST_REFUSAL = "yeh main abhi nahi kar sakta — abhi sirf YouTube khol sakta hoon, koi site khol sakta hoon, ya web search kar sakta hoon."


def _log_action(line: str) -> None:
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with BRAIN_MEMORY_MD.open("a", encoding="utf-8") as f:
            f.write(f"- {ts} — {line}\n")
    except Exception:
        pass


def _open_url(url: str) -> bool:
    """Open a URL via macOS `open` — no shell, http(s) only, defense in depth
    even though every caller here already builds the URL itself."""
    if not (url.startswith("https://") or url.startswith("http://")):
        return False
    try:
        subprocess.run(["open", url], check=True, timeout=5)
        return True
    except Exception:
        return False


def try_action(msg: str):
    """Whitelist-only intent check, run BEFORE the message reaches the LLM.
    Returns a reply dict if an action was executed, else None (falls through
    to the normal chat pipeline)."""
    msg = msg.strip()

    m = PLAY_RE.match(msg)
    if m:
        query = m.group(1).strip()
        url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
        if _open_url(url):
            _log_action(f'ACTION: opened YouTube search for "{query}"')
            return {"reply": f"YouTube khol diya: {query} 🎵", "action": "youtube_search"}
        return None

    m = OPEN_RE.match(msg)
    if m:
        site = re.sub(r"^https?://", "", m.group(1).strip(), flags=re.I)
        if _DOMAIN_RE.fullmatch(site):
            url = "https://" + site
            if _open_url(url):
                _log_action(f"ACTION: opened {url}")
                return {"reply": f"{site} khol diya.", "action": "open_site"}
        return None

    m = SEARCH_RE.match(msg)
    if m:
        query = m.group(1).strip()
        url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
        if _open_url(url):
            _log_action(f'ACTION: opened Google search for "{query}"')
            return {"reply": f"Google search khol diya: {query} 🔎", "action": "google_search"}
        return None

    if UNSUPPORTED_RE.match(msg):
        return {"reply": HONEST_REFUSAL, "action": "refused"}

    return None


CORS_ORIGIN = "http://localhost:8080"  # dashboard.html's static server


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", CORS_ORIGIN)
        self.end_headers()
        try:
            self.wfile.write(data)
        except Exception:
            pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", CORS_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _json_body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if self.path == "/bg.png":
            p = BASE / "bg.png"
            return self._send(200, p.read_bytes(), "image/png") if p.exists() else self._send(404, b"", "image/png")
        if self.path == "/bg.mp4":
            p = BASE / "bg.mp4"
            return self._send(200, p.read_bytes(), "video/mp4") if p.exists() else self._send(404, b"", "video/mp4")
        if self.path == "/notes":
            return self._send(200, json.dumps({"notes": notes_list()}))
        if self.path.startswith("/note?"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            return self._send(200, json.dumps(note_content((q.get("name") or [""])[0]) or {"error": "not found"}))
        if self.path == "/history":
            return self._send(200, json.dumps({"history": load_history()}))
        if self.path == "/config":
            c = load_cfg(); c["has_key"] = bool(c.pop("anthropic_api_key", ""))
            return self._send(200, json.dumps(c))
        self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if self.path in ("/chat", "/api/chat"):
            msg = (self._json_body().get("message") or "").strip()
            if not msg:
                return self._send(400, json.dumps({"error": "empty"}))
            action = try_action(msg)   # whitelist-only, checked before the LLM
            if action:
                result = action
            else:
                cfg = load_cfg()
                if cfg.get("prefer") == "opus" and cfg.get("anthropic_api_key"):
                    result = agent_respond(msg)   # Opus → acting agent
                else:
                    result = respond(msg)          # local → plain chat
            if self.path == "/api/chat":
                return self._send(200, json.dumps({"reply": result.get("reply", "")}))
            return self._send(200, json.dumps(result))
        if self.path == "/config":
            body = self._json_body(); cfg = load_cfg()
            key = body.pop("anthropic_api_key", None)
            if key:
                _keychain_set(KEYCHAIN_SERVICE, key)  # goes to Keychain, never to disk
            for k in ("prefer", "local_model"):
                if k in body and body[k] != "":
                    cfg[k] = body[k]
            cfg.pop("anthropic_api_key", None)
            save_json(CFG_FILE, cfg)
            return self._send(200, json.dumps({"ok": True}))
        if self.path == "/vision":
            b = self._json_body()
            img = b.get("image") or ""
            if not img:
                return self._send(400, json.dumps({"error": "no image"}))
            return self._send(200, json.dumps(vision_respond((b.get("message") or "").strip(), img)))
        if self.path == "/reset":
            save_json(MEM_FILE, [])
            return self._send(200, json.dumps({"ok": True}))
        self._send(404, json.dumps({"error": "not found"}))


if __name__ == "__main__":
    print(f"🧠 Second Brain — http://localhost:{PORT}")
    print(f"   vault: {VAULT}")
    print(f"   offline model: {load_cfg().get('local_model')}  (needs Ollama running)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

# NEURON 🧠 — personal AI "second brain" system

An Obsidian vault + local file watcher + Claude Code `CLAUDE.md` pattern for
running a personal agent system: task tracking, lead pipeline, outreach
drafting, and a local chat UI — all file-based, no cloud database.

## Architecture

```
vault (Obsidian, all markdown)
  ├── CLAUDE.md        → Claude Code reads this every session (agent roles + rules)
  ├── PROFILE.md / TASKS.md → your context, read every session
  ├── leads/, drafts/, projects/  → working data (not included here — see below)
  │
  ├── watcher.py       → indexes the vault into brain_index.json (graph, activity, focus)
  ├── dashboard.html    → visualizes that index (open via a local static server)
  ├── brain_chat.py     → local web app (localhost:8090): chat over your notes,
  │                        offline (Ollama) or online (Opus, via Keychain key)
  └── scripts/
        ├── find_leads.py   → Google Places lead-gen into leads/inbox/
        └── morning_run.sh  → daily driver, pulls API key from macOS Keychain
```

## Setup
```bash
pip3 install watchdog requests
# Optional local model:
ollama pull qwen2.5:3b
ollama pull moondream   # for screen/image chat

# API keys: Keychain only, never in a file.
security add-generic-password -a "$USER" -s anthropic_api_key -w 'YOUR-ANTHROPIC-KEY' -U
security add-generic-password -a "$USER" -s google_places_api_key -w '...' -U

cp brain_chat_config.example.json brain_chat_config.json
python3 brain_chat.py   # → http://localhost:8090
python3 watcher.py "$HOME/second-brain"
python3 -m http.server 8080   # serve dashboard.html
```

## The agent-roles pattern
`CLAUDE.md` defines five agent modes (Scout/Writer/Builder/Tracker/Professor)
and a set of hard rules (never auto-send, never fabricate, never commit
secrets). Copy `CLAUDE.md` into your own vault root and fill in `PROFILE.md`
/ `TASKS.md` — that's the whole system. Reuse the roles/rules, replace the
specifics.

## Honest state
- `brain_chat.py` — code is complete and was manually tested; not run as a
  long-lived service.
- `watcher.py` — works; by design it does **not** do TTS, screenshots, or run
  a network listener (see its own docstring).
- `find_leads.py` / `morning_run.sh` — functional; not on a schedule (no cron/
  LaunchAgent) — run manually.
- No STT, computer-control, or auto-posting modules exist in this repo —
  don't claim otherwise if you fork this.

## What's intentionally NOT in this repo
Personal data stays local and private: your `PROFILE.md`/`TASKS.md` content,
`leads/`, `internships/`, `drafts/`, `logs/`, client project folders,
`brain_memory.md`, `brain_index.json`, and any API keys. Keys live in macOS
Keychain only — never in a committed file.

## License
MIT

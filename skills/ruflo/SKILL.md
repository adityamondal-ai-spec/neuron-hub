---
name: ruflo
description: Multi-agent orchestration/memory tool (claude-flow fork) registered as the `claude-flow` MCP server. Use when a task needs multiple coordinating agents, swarm-style parallel work, or persistent vector memory across sessions — bigger jobs than one Builder/Scout pass can handle.
---

# Ruflo Skill — Neuron

## Kya hai
`ruflo` npm package hai (`npx ruflo@latest`), claude-flow se derive hua multi-agent
coordination layer. Project source: `~/Desktop/ruflo` (apna `CLAUDE.md`, 30 bundled
skills, `.claude-flow/`, `.swarm/memory.db`).

Installed 2026-07-15. MCP server registered globally as `claude-flow` —
`claude mcp add claude-flow -- npx -y ruflo@latest mcp start`. Har Claude Code
session (yeh vault included) mein already available hai, alag se setup nahi chahiye.

## Kab use karo
- Kaam 3+ files span kare, ya alag roles chahiye ho (research → build → test → review)
  jo NEURON ke standard Scout/Writer/Builder/Tracker se bada ho.
- Client project bada ho aur parallel sub-agents se fast ho sake (e.g. ek client site
  ka multiple pages/components ek saath banana).
- Cross-session pattern memory chahiye ho — `memory search`/`memory store` se pehle
  ke successful approaches recall karo.

## Kab NAHI
- Chhota kaam (1-2 file edit, single email draft, quick lead update) — NEURON ke
  normal agents (Scout/Writer/Builder/Tracker) hi kaafi hain, ruflo overkill hai.

## Kaise use karo
- MCP tools `mcp__claude-flow__*` prefix se available — `ToolSearch` se discover karo.
- CLI fallback: `npx ruflo@latest <command>` (Bash se), e.g.
  `npx ruflo@latest swarm init --topology hierarchical --max-agents 8`.
- Health check kabhi bhi: `npx ruflo@latest doctor --fix`.

## Note
Ek legacy `ruflo`-keyed MCP registration (project-scoped, `~/Desktop/ruflo`) canonical
`claude-flow` key ke saath duplicate hai — abhi tak clean nahi hua (2026-07-15 tak).

## Related
- [[🧠 NEURON HUB|NEURON HUB]]
- [[CLAUDE]]

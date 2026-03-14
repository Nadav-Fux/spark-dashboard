# Spark Mission Control — Design Spec
**Date:** 2026-03-14
**Status:** Implemented & Live at spark.74111147.xyz

---

## Problem

The original dashboard was passive — it showed static data but offered no way to act on anything:
- Cron entries showed raw syntax (`*/10 * * * *`) with full paths — unreadable
- Sites were a list of 4 static items, not clickable
- Jobs Feed had no meaningful data
- Chat ("Ask Spark Anything") was non-functional
- No container log access or restart capability
- No connection to n8n workflow execution history

---

## Solution Architecture

### Backend (FastAPI · `/root/spark-dashboard/backend/app.py`)

Five new API endpoints added alongside the existing ones:

| Endpoint | Purpose |
|---|---|
| `GET /api/executions` | Proxies n8n REST API — returns 25 most recent workflow runs with name, status, duration, trigger mode |
| `GET /api/logs/{name}` | Reads Docker socket multiplexed stream (8-byte frame headers) for any container |
| `POST /api/cron/explain` | Calls Nemotron AI with schedule + command, returns plain-English explanation; cached in memory |
| `POST /api/container/{name}/restart` | Sends restart signal via Docker socket API |
| `GET /api/containers` | Extended to include `restart_count` via Docker inspect |
| `GET /api/chat` (improved) | Now injects live psutil stats (CPU/RAM/disk/uptime/containers/sites) into system prompt |

Host crontab mounted as read-only volume: `/var/spool/cron/crontabs/root:/host-crontab/root:ro`

### Frontend (Vanilla JS · `/root/spark-dashboard/frontend/index.html`)

#### Cron — Schedule Intelligence
- `humanCron(schedule)` translates raw cron expressions → "Every 10 min", "Daily at 08:00", "On boot", etc.
- `shortCmd(cmd)` extracts filename from full path, strips extension, humanizes separators
- Click any cron row → AI explains it in a modal (cached after first call)
- Heatmap shows activity intensity per weekday/hour with min-max normalized colors
- Day labels (Sun–Sat) shown on left

#### Containers
- Each card shows: name, image, status badge, restart count
- "View Logs" button → fetches `/api/logs/{name}` → log modal with stdout/stderr color coding
- "Restart" button → POST to `/api/container/{name}/restart`

#### Sites
- All site entries are `<a>` tags opening in new tab
- Response time color-coded: green <300ms, yellow slow, red unreachable

#### Automation Activity (replaces Jobs Feed)
- Pulls `/api/executions` → real n8n workflow run history
- Shows: workflow name, status badge (success/error/running), trigger mode, time-ago, duration in seconds

#### Chat
- Sends live dashboard snapshot (CPU/RAM/disk/uptime/container list/site statuses) with every message
- Chat panel has close button; history preserved per session

#### Hero Animation (Three.js)
Two modes alternating every 7 seconds via GSAP cross-fade:
1. **Orbital Core** — nested icosahedra (4.2, 7.0 radius), dodecahedron inner core, octahedron shell, 28 floating particles — all amber/copper tones
2. **Container Topology** — octahedron nodes arranged in ring with LineBasicMaterial edges, faint icosahedron background

`switchThreeMode()` fades material opacities with `gsap.to` over 1.8s, label updates with fade ("Orbital Core" ↔ "Container Topology").

#### Auto-refresh intervals
- Stats: 30s
- Containers + Sites: 60s
- Executions: 90s
- Cron: 120s

---

## n8n Email Migration

Four workflows migrated from SMTP → AgentMail API:
- `wmf6LIDtqemxv5hn` — Crypto Alert (2 email nodes)
- `v52TRta2nRpWIArU` — Surprise Research (1 node)
- `SVLluuyyoUQf6eay` — Site Watchdog (1 node)

All now POST to `https://api.agentmail.to/v0/inboxes/sparkemail@agentmail.to/messages/send` with Bearer auth — no SMTP credentials needed in n8n.

---

## Key Decisions

- **No jQuery for new code** — vanilla JS throughout; existing jQuery calls preserved
- **Docker socket directly** — log streaming via `/var/run/docker.sock` UDS, avoids docker CLI dependency
- **Nemotron for cron explanations** — same model as chat, results cached in-process dict
- **IntersectionObserver for scroll reveal** — sections fade up on first scroll into view
- **No regular emoji** — design language uses SVG icons and geometric shapes only

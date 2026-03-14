# Spark Mission Control — Implementation Plan
**Date:** 2026-03-14
**Status:** Completed

---

## Phase 1 — n8n Email Migration
1. Identify workflows using SMTP: Crypto Alert, Surprise Research, Site Watchdog
2. For each workflow: GET full JSON via n8n REST API, swap `emailSend` nodes for `httpRequest` nodes targeting AgentMail API
3. PUT updated workflow JSON back (strip extra fields: `id`, `createdAt`, `updatedAt`, `versionId`)
4. Verify updated node configs in n8n UI

## Phase 2 — Backend Endpoints
1. Add `struct` import for Docker log frame parsing
2. Add `N8N_API_KEY` + `N8N_BASE` constants
3. Add `_cron_cache: dict` for AI explanation caching
4. Add `_docker_client()` context manager (Unix socket transport)
5. Implement `GET /api/executions` — fetch workflows list + executions, compute durations
6. Implement `GET /api/logs/{name}` — parse Docker multiplexed stream (8-byte headers)
7. Implement `POST /api/cron/explain` — Nemotron call with caching
8. Implement `POST /api/container/{name}/restart`
9. Extend `GET /api/containers` to include `restart_count`
10. Improve `POST /api/chat` system prompt with live psutil stats injection

## Phase 3 — Frontend Rewrite
1. Add `humanCron()` + `shortCmd()` utility functions
2. Rewrite `fetchCron()` — human-readable rows + click handler
3. Add `showCronExplain()` — modal + AI call
4. Rewrite `fetchSites()` — clickable `<a>` tags + color-coded response times
5. Add `fetchExecutions()` — replaces `fetchJobs()`, calls `/api/executions`
6. Rewrite `fetchContainers()` — add View Logs + Restart buttons
7. Add `showLogs(name)` — log modal with stream coloring
8. Improve chat panel — live context injection + close button
9. Add heatmap day labels (`#hmDays`)
10. Set auto-refresh intervals (30s/60s/90s/120s)

## Phase 4 — Three.js Dual Animation
1. Separate existing topology code into `topoGroup`
2. Build `icoGroup` — nested icosahedra (4 geometries) + 28 particles
3. Add `threeMode` toggle variable + `#threeLabel` element
4. Implement `switchThreeMode()` with GSAP cross-fade (1.8s ease)
5. Set `setInterval(switchThreeMode, 7000)`
6. Start in Orbital Core mode (`threeMode = 0`)

## Phase 5 — Deploy
1. Mount host crontab: `-v /var/spool/cron/crontabs/root:/host-crontab/root:ro`
2. `docker build -t spark-dashboard .`
3. `docker stop spark-dashboard && docker rm spark-dashboard`
4. `docker run -d` with all mounts (data volume, docker.sock, crontab)
5. Verify all endpoints from inside container
6. Smoke test via browser: animations, cron count, logs modal, chat

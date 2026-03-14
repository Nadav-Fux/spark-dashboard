"""
Spark Server Dashboard - FastAPI Backend  v2
Runs on 77.90.40.84:8888
"""

import json
import os
import re
import struct
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import psutil
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NVIDIA_API_KEY = os.getenv(
    "NVIDIA_API_KEY",
    "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",
)
NVIDIA_MODEL = "nvidia/nemotron-3-super-120b-a12b"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

N8N_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZjc5Mjc4Mi1kZjJiLTRiNWEtYmZjYS01NGMyNWQ2YmMxYjAiLCJpc3MiOiJuOG4iLCJhdWQiOiJwdWJsaWMtYXBpIiwianRpIjoiYTU3YjRiZTMtZTQxMi00NTYzLWJkZTMtY2NkNmY3NThhNTNkIiwiaWF0IjoxNzcwMzk4MjU3fQ.njnXxNgQ8974YpqyZ4CKi2Z8Uy-s4kPuLlcHxA6jFQ0"
N8N_BASE = "https://n8n.74111147.xyz/api/v1"

SITES_TO_CHECK = [
    "https://log.nvision.me",
    "https://prompts.nvision.me",
    "https://yt.nvision.me",
    "https://n8n.74111147.xyz",
]

JOBS_FILE = Path("/root/spark-dashboard/data/jobs.json")

SYSTEM_PROMPT = """You are Spark — the intelligent operations AI for the Spark server (77.90.40.84).
You have full knowledge of this infrastructure and can help troubleshoot, explain, and suggest improvements.

## Infrastructure
- Host: Spark server 77.90.40.84 (Debian/Ubuntu Linux)
- Containers on fortress-network: openclaw-gateway, fortress-n8n, spark-dashboard, and more
- Sites: log.nvision.me, prompts.nvision.me, yt.nvision.me, n8n.74111147.xyz
- n8n workflows: Morning Brief (daily 8am), Crypto Alert, Surprise Research, Site Watchdog
- Email: sparkemail@agentmail.to → nadavf@gmail.com

## Key Paths
- /tmp/spark-journal/: Spark Log repo
- /tmp/prompt-gallery/: Prompt Gallery
- /root/yt-research/: YT Research repo
- /root/spark-dashboard/: This dashboard

## APIs in use
- NVIDIA NIM (Nemotron 3 Super 120B) — AI inference
- CoinGecko — crypto prices
- SerpAPI — news search
- Alpaca — paper trading portfolio
- AgentMail — email delivery

Answer concisely. If uncertain, say so and suggest where to look."""

# In-memory cache for cron explanations
_cron_cache: dict[str, str] = {}

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Spark Dashboard API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    history: list[dict[str, str]] = []
    context: dict[str, Any] | None = None  # live system state from frontend

class ChatResponse(BaseModel):
    reply: str
    model: str

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], timeout: int = 10) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception as e:
        return f"ERROR: {e}"

def _fmt(b: int) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if abs(b) < 1024:
            return f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} PB"

def _uptime() -> str:
    boot = datetime.fromtimestamp(psutil.boot_time(), tz=timezone.utc)
    delta = datetime.now(timezone.utc) - boot
    days, rem = divmod(int(delta.total_seconds()), 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    parts = []
    if days: parts.append(f"{days}d")
    if hours: parts.append(f"{hours}h")
    parts.append(f"{mins}m")
    return " ".join(parts)

def _docker_client():
    transport = httpx.HTTPTransport(uds="/var/run/docker.sock")
    return httpx.Client(transport=transport, base_url="http://docker", timeout=10)

# ---------------------------------------------------------------------------
# 1. GET /api/stats
# ---------------------------------------------------------------------------

@app.get("/api/stats")
async def get_stats():
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    load1, load5, load15 = psutil.getloadavg()
    net = psutil.net_io_counters()
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "cpu_count": psutil.cpu_count(),
        "ram": {"used": _fmt(mem.used), "total": _fmt(mem.total), "percent": mem.percent},
        "disk": {"used": _fmt(disk.used), "total": _fmt(disk.total), "percent": disk.percent},
        "uptime": _uptime(),
        "load_average": {"1m": round(load1, 2), "5m": round(load5, 2), "15m": round(load15, 2)},
        "network": {"sent": _fmt(net.bytes_sent), "recv": _fmt(net.bytes_recv)},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

# ---------------------------------------------------------------------------
# 2. GET /api/containers
# ---------------------------------------------------------------------------

@app.get("/api/containers")
async def get_containers():
    try:
        with _docker_client() as client:
            data = client.get("/containers/json?all=true").json()
        result = []
        for c in data:
            ports = c.get("Ports", [])
            ports_str = ", ".join(
                f"{p.get('PublicPort','')}:{p.get('PrivatePort','')}" if p.get("PublicPort")
                else f"{p.get('PrivatePort','')}/{p.get('Type','tcp')}"
                for p in ports
            )
            names = [n.lstrip("/") for n in c.get("Names", [])]
            # Get restart count from inspect
            restart_count = 0
            try:
                cid = c.get("Id", "")[:12]
                inspect = client.get(f"/containers/{cid}/json").json()
                restart_count = inspect.get("RestartCount", 0)
            except Exception:
                pass
            result.append({
                "name": names[0] if names else "unknown",
                "id": c.get("Id", "")[:12],
                "status": c.get("Status", ""),
                "state": c.get("State", ""),
                "ports": ports_str,
                "image": c.get("Image", ""),
                "restart_count": restart_count,
            })
        return result
    except Exception as e:
        raise HTTPException(500, f"Docker error: {e}")

# ---------------------------------------------------------------------------
# 3. GET /api/cron
# ---------------------------------------------------------------------------

@app.get("/api/cron")
async def get_cron():
    cron_path = Path("/host-crontab/root")
    raw = cron_path.read_text() if cron_path.exists() else _run(["crontab", "-l"])
    if raw.startswith("ERROR") or "no crontab" in raw.lower():
        return []
    entries = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^(@\w+|(?:\S+\s+){5})(.*)", line)
        if match:
            schedule = match.group(1).strip()
            command = match.group(2).strip()
            short = (command[:80] + "...") if len(command) > 80 else command
            entries.append({"schedule": schedule, "command": short, "full_command": command})
    return entries

# ---------------------------------------------------------------------------
# 4. POST /api/cron/explain
# ---------------------------------------------------------------------------

@app.post("/api/cron/explain")
async def explain_cron(body: dict):
    schedule = body.get("schedule", "")
    command = body.get("command", "")
    key = f"{schedule}|||{command}"
    if key in _cron_cache:
        return {"explanation": _cron_cache[key]}

    prompt = f"""Explain this Linux cron job simply for a server operator. Be specific.

Schedule: {schedule}
Command: {command}

Reply with exactly 3 short points (no headers, no markdown):
1. WHEN: translate the cron schedule to plain English (e.g. "Every 10 minutes", "Daily at 3 AM")
2. WHAT: what this command likely does based on its name and path
3. WHY: why this matters on a production server

Keep each point to 1-2 sentences. Be concrete, not generic."""

    messages = [
        {"role": "system", "content": "You are a Linux server expert. Give precise, concise explanations."},
        {"role": "user", "content": prompt},
    ]
    payload = {"model": NVIDIA_MODEL, "messages": messages, "temperature": 0.3, "max_tokens": 350}
    headers = {"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.post(NVIDIA_BASE_URL, headers=headers, json=payload)
            r.raise_for_status()
            reply = r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            reply = f"Could not generate explanation: {e}"

    _cron_cache[key] = reply
    return {"explanation": reply}

# ---------------------------------------------------------------------------
# 5. GET /api/sites
# ---------------------------------------------------------------------------

@app.get("/api/sites")
async def get_sites():
    results = []
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        for url in SITES_TO_CHECK:
            t0 = time.monotonic()
            try:
                r = await client.get(url)
                ms = round((time.monotonic() - t0) * 1000)
                results.append({"url": url, "status_code": r.status_code, "response_time_ms": ms, "ok": 200 <= r.status_code < 400})
            except Exception as e:
                ms = round((time.monotonic() - t0) * 1000)
                results.append({"url": url, "status_code": None, "response_time_ms": ms, "ok": False, "error": str(e)})
    return results

# ---------------------------------------------------------------------------
# 6. GET /api/executions  (n8n workflow history)
# ---------------------------------------------------------------------------

@app.get("/api/executions")
async def get_executions():
    headers = {"X-N8N-API-KEY": N8N_API_KEY}
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            wf_resp = await client.get(f"{N8N_BASE}/workflows?limit=50", headers=headers)
            wf_map = {w["id"]: w["name"] for w in wf_resp.json().get("data", [])}
            ex_resp = await client.get(f"{N8N_BASE}/executions?limit=25", headers=headers)
            execs = ex_resp.json().get("data", [])
        except Exception as e:
            raise HTTPException(502, f"n8n API error: {e}")

    result = []
    for ex in execs:
        started = ex.get("startedAt")
        stopped = ex.get("stoppedAt")
        duration_s = None
        if started and stopped:
            try:
                s = datetime.fromisoformat(started.replace("Z", "+00:00"))
                e2 = datetime.fromisoformat(stopped.replace("Z", "+00:00"))
                duration_s = round((e2 - s).total_seconds(), 1)
            except Exception:
                pass
        result.append({
            "id": ex.get("id"),
            "workflow": wf_map.get(ex.get("workflowId"), "Unknown"),
            "workflowId": ex.get("workflowId"),
            "status": ex.get("status", "unknown"),
            "startedAt": started,
            "stoppedAt": stopped,
            "duration_s": duration_s,
            "mode": ex.get("mode", ""),
        })
    return result

# ---------------------------------------------------------------------------
# 7. GET /api/logs/{name}
# ---------------------------------------------------------------------------

@app.get("/api/logs/{name}")
async def get_logs(name: str, lines: int = 60):
    try:
        with _docker_client() as client:
            resp = client.get(f"/containers/{name}/logs?tail={lines}&stderr=1&stdout=1&timestamps=1", timeout=15)
            raw = resp.content

        # Docker log stream: 8-byte header per frame [stream(1), padding(3), size(4)]
        log_lines = []
        i = 0
        while i + 8 <= len(raw):
            stream_type = raw[i]
            size = struct.unpack(">I", raw[i+4:i+8])[0]
            if i + 8 + size > len(raw):
                break
            line = raw[i+8:i+8+size].decode("utf-8", errors="replace").rstrip("\n")
            if line.strip():
                log_lines.append({
                    "stream": "stderr" if stream_type == 2 else "stdout",
                    "line": line,
                })
            i += 8 + size

        return {"name": name, "logs": log_lines[-lines:]}
    except Exception as e:
        raise HTTPException(500, f"Log error: {e}")

# ---------------------------------------------------------------------------
# 8. POST /api/container/{name}/restart
# ---------------------------------------------------------------------------

@app.post("/api/container/{name}/restart")
async def restart_container(name: str):
    try:
        with _docker_client() as client:
            r = client.post(f"/containers/{name}/restart", timeout=30)
        if r.status_code not in (204, 200):
            raise HTTPException(r.status_code, f"Docker returned {r.status_code}")
        return {"status": "ok", "container": name}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Restart error: {e}")

# ---------------------------------------------------------------------------
# 9. POST /api/chat
# ---------------------------------------------------------------------------

@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    # Build live context snippet
    try:
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        load1, _, _ = psutil.getloadavg()
        live = (
            f"\n\n## Live system state ({datetime.now(timezone.utc).strftime('%H:%M UTC')})\n"
            f"- CPU: {psutil.cpu_percent(interval=0.2):.1f}%\n"
            f"- RAM: {mem.percent:.1f}% used ({_fmt(mem.used)} / {_fmt(mem.total)})\n"
            f"- Disk: {disk.percent:.1f}% used\n"
            f"- Load 1m: {load1:.2f}\n"
            f"- Uptime: {_uptime()}\n"
        )
    except Exception:
        live = ""

    # If frontend passed extra context (containers, etc.)
    if req.context:
        try:
            live += f"- Dashboard context: {json.dumps(req.context)[:500]}\n"
        except Exception:
            pass

    messages = [{"role": "system", "content": SYSTEM_PROMPT + live}]
    for msg in req.history[-12:]:
        if msg.get("role") in ("user", "assistant") and msg.get("content"):
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": req.message})

    headers = {"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": NVIDIA_MODEL, "messages": messages, "temperature": 0.65, "top_p": 0.9, "max_tokens": 1024}

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            r = await client.post(NVIDIA_BASE_URL, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, f"NVIDIA API: {e.response.text}")
        except Exception as e:
            raise HTTPException(502, f"AI unavailable: {e}")

    reply = data.get("choices", [{}])[0].get("message", {}).get("content", "No response.")
    return ChatResponse(reply=reply, model=NVIDIA_MODEL)

# ---------------------------------------------------------------------------
# 10. GET /api/jobs  &  POST /api/jobs
# ---------------------------------------------------------------------------

@app.get("/api/jobs")
async def get_jobs():
    if not JOBS_FILE.exists():
        return []
    try:
        data = json.loads(JOBS_FILE.read_text())
        return data if isinstance(data, list) else [data]
    except Exception as e:
        raise HTTPException(500, f"Jobs read error: {e}")

@app.post("/api/jobs")
async def post_job(job: dict[str, Any]):
    entry = {
        "id": job.get("jobId") or job.get("id") or f"job-{int(time.time())}",
        "type": job.get("type", "info"),
        "title": job.get("title") or job.get("type", "Automation Result"),
        "content": job.get("content") or json.dumps(job.get("data", {}))[:500],
        "status": job.get("status", "success"),
        "timestamp": job.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        "details": job.get("details", ""),
        "name": job.get("name") or job.get("title") or "Job",
    }
    jobs: list = []
    if JOBS_FILE.exists():
        try:
            d = json.loads(JOBS_FILE.read_text())
            jobs = d if isinstance(d, list) else [d]
        except Exception:
            pass
    jobs.insert(0, entry)
    JOBS_FILE.write_text(json.dumps(jobs[:50], indent=2))
    return {"status": "ok", "id": entry["id"]}

# ---------------------------------------------------------------------------
# Health + Frontend
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

FRONTEND_DIR = Path("/root/spark-dashboard/frontend")

@app.get("/")
async def serve_frontend():
    return FileResponse(FRONTEND_DIR / "index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8888)

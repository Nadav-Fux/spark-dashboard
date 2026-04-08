"""
Spark Server Dashboard - FastAPI Backend
Runs on 77.90.40.84:8888
"""

import json
import os
import re
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
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NVIDIA_API_KEY = os.getenv(
    "NVIDIA_API_KEY",
    "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",
)
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-super-120b-a12b")
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

SITES_TO_CHECK = [
    "https://log.nvision.me",
    "https://prompts.nvision.me",
    "https://yt.nvision.me",
    "https://n8n.74111147.xyz",
]

JOBS_FILE = Path("/root/spark-dashboard/data/jobs.json")

N8N_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZjc5Mjc4Mi1kZjJiLTRiNWEtYmZjYS01NGMyNWQ2YmMxYjAiLCJpc3MiOiJuOG4iLCJhdWQiOiJwdWJsaWMtYXBpIiwianRpIjoiYTU3YjRiZTMtZTQxMi00NTYzLWJkZTMtY2NkNmY3NThhNTNkIiwiaWF0IjoxNzcwMzk4MjU3fQ.njnXxNgQ8974YpqyZ4CKi2Z8Uy-s4kPuLlcHxA6jFQ0"
N8N_BASE = "https://n8n.74111147.xyz/api/v1"

# In-process caches
_cron_cache: dict[str, str] = {}
_workflow_names: dict[str, str] = {}

SYSTEM_PROMPT = (
    "You are Spark, the intelligent operations assistant for the Spark server "
    "(77.90.40.84). You know everything about this infrastructure and can answer "
    "questions, troubleshoot, and suggest improvements.\n\n"
    "## Server overview\n"
    "- Host: Spark server at 77.90.40.84 (Debian/Ubuntu Linux)\n"
    "- Primary purpose: Hosting web apps, automation pipelines, and AI services\n\n"
    "## Docker containers running on Spark\n"
    "- openclaw-gateway: main gateway container (Python services)\n"
    "- fortress-n8n: n8n automation platform (https://n8n.74111147.xyz)\n"
    "- Additional containers may be present; check /api/containers for live data.\n\n"
    "## Hosted sites (Cloudflare Pages / Workers)\n"
    "- log.nvision.me: Spark Log (session journal, deployed via Wrangler)\n"
    "- prompts.nvision.me: Lovable Prompt Gallery (CF Pages)\n"
    "- yt.nvision.me: YouTube Research Dashboard (CF Pages + Worker + R2)\n"
    "- n8n.74111147.xyz: n8n automation UI\n\n"
    "## Automation and cron\n"
    "- Cron jobs handle backups, health-checks, and scheduled tasks.\n"
    "- n8n workflows handle YouTube scraping, email reports, and webhook processing.\n\n"
    "## Key paths\n"
    "- /tmp/spark-journal/: Spark Log repo\n"
    "- /tmp/prompt-gallery/: Prompt Gallery files\n"
    "- /root/yt-research/: YT Research repo\n"
    "- /root/spark-dashboard/: This dashboard\n\n"
    "## Email\n"
    "- sparkemail@agentmail.to: Spark report emails (to nadavf@gmail.com)\n"
    "- selaitay@agentmail.to: OpenClaw email\n\n"
    "## AI model\n"
    "- NVIDIA Nemotron-3 Super 120B (nvidia/nemotron-3-super-120b-a12b)\n"
    "- Via NVIDIA NIM API\n\n"
    "Answer concisely and helpfully. If you don't know something, say so and "
    "suggest how the user could find out (e.g. which endpoint to check, which "
    "command to run)."
)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Spark Dashboard API",
    version="1.0.0",
    description="Backend API for the Spark server dashboard",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str
    history: list[dict[str, str]] = []


class ChatResponse(BaseModel):
    reply: str
    model: str
    usage: dict[str, Any] | None = None


class CronExplainRequest(BaseModel):
    schedule: str
    command: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str], timeout: int = 10) -> str:
    """Run a subprocess and return stdout."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip()
    except Exception as exc:
        return f"ERROR: {exc}"


def _format_bytes(b: int) -> str:
    """Human-readable bytes."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(b) < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def _uptime_str() -> str:
    """Return human-readable uptime."""
    boot = datetime.fromtimestamp(psutil.boot_time(), tz=timezone.utc)
    delta = datetime.now(timezone.utc) - boot
    days = delta.days
    hours, rem = divmod(delta.seconds, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# 1. GET /api/stats
# ---------------------------------------------------------------------------


@app.get("/api/stats")
async def get_stats():
    """System stats: CPU, RAM, disk, uptime, load average."""
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    load1, load5, load15 = psutil.getloadavg()
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "cpu_count": psutil.cpu_count(),
        "ram": {
            "used": _format_bytes(mem.used),
            "total": _format_bytes(mem.total),
            "percent": mem.percent,
        },
        "disk": {
            "used": _format_bytes(disk.used),
            "total": _format_bytes(disk.total),
            "percent": disk.percent,
        },
        "uptime": _uptime_str(),
        "load_average": {
            "1m": round(load1, 2),
            "5m": round(load5, 2),
            "15m": round(load15, 2),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# 2. GET /api/containers
# ---------------------------------------------------------------------------


@app.get("/api/containers")
async def get_containers():
    """List all Docker containers via Docker socket API."""
    import httpx
    try:
        transport = httpx.HTTPTransport(uds="/var/run/docker.sock")
        with httpx.Client(transport=transport, base_url="http://docker") as client:
            resp = client.get("/containers/json?all=true", timeout=10)
            data = resp.json()
        containers = []
        for c in data:
            ports_list = c.get("Ports", [])
            ports_str = ", ".join(
                f"{p.get('IP','0.0.0.0')}:{p.get('PublicPort','')}→{p.get('PrivatePort','')}/{p.get('Type','tcp')}"
                if p.get("PublicPort") else f"{p.get('PrivatePort','')}/{p.get('Type','tcp')}"
                for p in ports_list
            )
            names = [n.lstrip("/") for n in c.get("Names", [])]
            containers.append({
                "name": names[0] if names else "unknown",
                "status": c.get("Status", ""),
                "ports": ports_str,
                "uptime": c.get("Status", ""),
                "image": c.get("Image", ""),
            })
        return containers
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Docker API error: {exc}")


# ---------------------------------------------------------------------------
# 3. GET /api/cron
# ---------------------------------------------------------------------------


@app.get("/api/cron")
async def get_cron():
    """Parse and return crontab entries."""
    # Try host crontab file (mounted) first, then subprocess
    cron_path = Path("/host-crontab/root")
    if cron_path.exists():
        raw = cron_path.read_text()
    else:
        raw = _run(["crontab", "-l"])
    if raw.startswith("ERROR") or "no crontab" in raw.lower():
        return []
    entries = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Standard cron: 5 time fields + command
        match = re.match(r"^(@\w+|(?:\S+\s+){5})(.*)", line)
        if match:
            schedule = match.group(1).strip()
            command = match.group(2).strip()
            short_cmd = (command[:80] + "...") if len(command) > 80 else command
            entries.append({
                "schedule": schedule,
                "command": short_cmd,
                "full_command": command,
                "last_run_status": "unknown",
            })
        else:
            entries.append({
                "schedule": "parse-error",
                "command": line[:80],
                "full_command": line,
                "last_run_status": "unknown",
            })
    return entries


# ---------------------------------------------------------------------------
# 3b. POST /api/cron/explain
# ---------------------------------------------------------------------------


@app.post("/api/cron/explain")
async def explain_cron(req: CronExplainRequest):
    """Return a plain-English explanation of a cron job (cached in memory)."""
    cache_key = f"{req.schedule}||{req.command}"
    if cache_key in _cron_cache:
        return {"explanation": _cron_cache[cache_key]}

    prompt = (
        f"Explain this cron job in plain English (2-3 sentences max):\n"
        f"Schedule: {req.schedule}\n"
        f"Command: {req.command}\n\n"
        f"Describe: when it runs, what it does, and why it likely exists on a Linux server."
    )
    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": NVIDIA_MODEL,
        "messages": [
            {"role": "system", "content": "You are a Linux systems expert. Answer concisely."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 256,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(NVIDIA_BASE_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            explanation = data["choices"][0]["message"]["content"].strip()
            _cron_cache[cache_key] = explanation
            return {"explanation": explanation}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"AI API error: {exc}")


# ---------------------------------------------------------------------------
# 3c. GET /api/executions — n8n workflow run history
# ---------------------------------------------------------------------------


async def _get_workflow_names() -> dict[str, str]:
    """Fetch and cache n8n workflow id→name mapping."""
    if _workflow_names:
        return _workflow_names
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{N8N_BASE}/workflows?limit=50",
                headers={"X-N8N-API-KEY": N8N_API_KEY},
            )
            resp.raise_for_status()
            for wf in resp.json().get("data", []):
                _workflow_names[wf["id"]] = wf["name"]
    except Exception:
        pass
    return _workflow_names


@app.get("/api/executions")
async def get_executions():
    """Return 25 most recent n8n workflow executions with workflow names."""
    names = await _get_workflow_names()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{N8N_BASE}/executions?limit=25",
                headers={"X-N8N-API-KEY": N8N_API_KEY},
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"n8n API error: {exc}")

    result = []
    for ex in data:
        started = ex.get("startedAt")
        stopped = ex.get("stoppedAt")
        dur = None
        if started and stopped:
            try:
                s = datetime.fromisoformat(started.replace("Z", "+00:00"))
                e = datetime.fromisoformat(stopped.replace("Z", "+00:00"))
                dur = round((e - s).total_seconds(), 1)
            except Exception:
                pass
        wf_id = ex.get("workflowId", "")
        result.append({
            "id": ex["id"],
            "workflow": names.get(wf_id, wf_id or "Unknown"),
            "workflowId": wf_id,
            "status": ex.get("status", "unknown"),
            "mode": ex.get("mode"),
            "startedAt": started,
            "duration_s": dur,
        })
    return result


# ---------------------------------------------------------------------------
# 3d. GET /api/workflow-debug/{workflow_id}
# ---------------------------------------------------------------------------


@app.get("/api/workflow-debug/{workflow_id}")
async def workflow_debug(workflow_id: str):
    """Return workflow JSON + last error + ready-to-paste Claude Code prompt."""
    h = {"X-N8N-API-KEY": N8N_API_KEY}
    async with httpx.AsyncClient(timeout=15) as client:
        # Workflow definition
        wf_resp = await client.get(f"{N8N_BASE}/workflows/{workflow_id}", headers=h)
        wf_resp.raise_for_status()
        wf_data = wf_resp.json()

        # Last failed execution (with node-level data)
        ex_resp = await client.get(
            f"{N8N_BASE}/executions?workflowId={workflow_id}&status=error&limit=1&includeData=true",
            headers=h,
        )
        ex_resp.raise_for_status()
        ex_list = ex_resp.json().get("data", [])

    # Extract error message(s) from execution run data
    last_error = "No error details found"
    if ex_list:
        ex = ex_list[0]
        run_data = (ex.get("data") or {}).get("resultData", {}).get("runData", {})
        errors = []
        for node_name, runs in run_data.items():
            for run in runs or []:
                err = run.get("error")
                if err:
                    msg = err.get("message") or err.get("description") or str(err)
                    errors.append(f"Node '{node_name}': {msg}")
        if errors:
            last_error = "\n".join(errors)

    wf_name = wf_data.get("name", workflow_id)
    # Strip read-only fields before showing patch body
    skip = {"id", "createdAt", "updatedAt", "versionId"}
    patch_body = {k: v for k, v in wf_data.items() if k not in skip}

    prompt = (
        f'Fix this broken n8n workflow.\n\n'
        f'## Workflow: "{wf_name}" (ID: {workflow_id})\n\n'
        f'## Last error:\n{last_error}\n\n'
        f'## Full workflow JSON:\n{json.dumps(patch_body, indent=2)}\n\n'
        f'## n8n API access:\n'
        f'Base URL: {N8N_BASE}\n'
        f'Auth header: X-N8N-API-KEY: {N8N_API_KEY}\n\n'
        f'## To apply fix:\n'
        f'PUT {N8N_BASE}/workflows/{workflow_id}\n'
        f'Headers: {{"X-N8N-API-KEY": "{N8N_API_KEY}", "Content-Type": "application/json"}}\n'
        f'Body: corrected workflow JSON (omit id/createdAt/updatedAt/versionId)\n\n'
        f'Analyze the error, fix the broken node(s), apply via PUT, then confirm.'
    )

    return {
        "workflow_id": workflow_id,
        "workflow_name": wf_name,
        "last_error": last_error,
        "prompt": prompt,
    }


# ---------------------------------------------------------------------------
# 4. GET /api/sites
# ---------------------------------------------------------------------------


@app.get("/api/sites")
async def get_sites():
    """Check health of monitored sites."""
    results = []
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        for url in SITES_TO_CHECK:
            start = time.monotonic()
            try:
                resp = await client.get(url)
                elapsed = round((time.monotonic() - start) * 1000)
                results.append({
                    "url": url,
                    "status_code": resp.status_code,
                    "response_time_ms": elapsed,
                    "ok": 200 <= resp.status_code < 400,
                })
            except Exception as exc:
                elapsed = round((time.monotonic() - start) * 1000)
                results.append({
                    "url": url,
                    "status_code": None,
                    "response_time_ms": elapsed,
                    "ok": False,
                    "error": str(exc),
                })
    return results


# ---------------------------------------------------------------------------
# 5. POST /api/chat - Nemotron chatbot proxy
# ---------------------------------------------------------------------------


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Forward user message to NVIDIA Nemotron and return the reply."""
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Append conversation history
    for msg in req.history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    # Append current user message
    messages.append({"role": "user", "content": req.message})

    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": NVIDIA_MODEL,
        "messages": messages,
        "temperature": 0.6,
        "top_p": 0.9,
        "max_tokens": 2048,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            resp = await client.post(NVIDIA_BASE_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=exc.response.status_code,
                detail=f"NVIDIA API error: {exc.response.text}",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to reach NVIDIA API: {exc}",
            )

    choice = data.get("choices", [{}])[0]
    reply = choice.get("message", {}).get("content", "")
    usage = data.get("usage")
    return ChatResponse(reply=reply, model=NVIDIA_MODEL, usage=usage)


# ---------------------------------------------------------------------------
# 6. GET /api/jobs - automation job results
# ---------------------------------------------------------------------------


@app.get("/api/jobs")
async def get_jobs():
    """Return automation job results from jobs.json."""
    if not JOBS_FILE.exists():
        return []
    try:
        data = json.loads(JOBS_FILE.read_text())
        if isinstance(data, list):
            return data
        return [data]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read jobs file: {exc}")


@app.post("/api/jobs")
async def post_job(job: dict[str, Any]):
    """Accept a new job result from n8n or other automation sources."""
    # Normalize the job entry for the frontend
    entry = {
        "id": job.get("jobId") or job.get("id") or f"job-{int(time.time())}",
        "type": job.get("type", "info"),
        "title": job.get("title") or job.get("type", "Automation Result"),
        "content": job.get("content") or json.dumps(job.get("data", {}))[:500],
        "status": job.get("status", "success"),
        "timestamp": job.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        "details": job.get("details", ""),
        "name": job.get("name") or job.get("title") or job.get("type", "Job"),
    }

    # Read existing jobs
    jobs: list[dict] = []
    if JOBS_FILE.exists():
        try:
            data = json.loads(JOBS_FILE.read_text())
            jobs = data if isinstance(data, list) else [data]
        except Exception:
            jobs = []

    # Prepend new job (newest first), keep max 50
    jobs.insert(0, entry)
    jobs = jobs[:50]

    JOBS_FILE.write_text(json.dumps(jobs, indent=2))
    return {"status": "ok", "id": entry["id"]}


# ---------------------------------------------------------------------------
# Health-check
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health():
    """Simple health-check endpoint."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

FRONTEND_DIR = Path("/root/spark-dashboard/frontend")


@app.get("/")
async def serve_frontend():
    """Serve the dashboard frontend."""
    return FileResponse(FRONTEND_DIR / "index.html")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8888)

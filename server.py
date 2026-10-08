"""Transient Hunter web server.

Run:  python server.py   then open http://localhost:8003
"""
import json
import queue
import threading
import time
import traceback
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from hunter import pipeline

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="Transient Hunter")
app.add_middleware(GZipMiddleware, minimum_size=2000)
jobs = {}
job_queue = queue.Queue()


class ScanRequest(BaseModel):
    days: int = 14
    min_prob: float = 0.4
    max_objects: int = 200


def worker():
    while True:
        jid = job_queue.get()
        job = jobs[jid]
        job["status"] = "running"

        def progress(pct, msg):
            job["pct"] = round(pct, 1)
            job["log"].append(msg)

        try:
            res = pipeline.scan(job["days"], job["min_prob"], job["max_objects"], progress)
            job.update(status="done", file=res["file"])
        except Exception as exc:
            traceback.print_exc()
            job.update(status="error", error=str(exc))
            job["log"].append(f"ERROR: {exc}")


threading.Thread(target=worker, daemon=True).start()


def _submit(req):
    jid = uuid.uuid4().hex[:10]
    jobs[jid] = {"id": jid, "status": "queued", "pct": 0, "log": [], "created": time.time(), **req.model_dump()}
    job_queue.put(jid)
    return jobs[jid]


@app.post("/api/scan")
def start_scan(req: ScanRequest):
    if not (1 <= req.days <= 60 and 0 <= req.min_prob <= 1 and 10 <= req.max_objects <= 500):
        raise HTTPException(400, "days 1–60, probability 0–1, objects 10–500")
    return _submit(req)


@app.get("/api/jobs")
def list_jobs():
    return sorted(({k: v for k, v in j.items() if k != "log"} for j in jobs.values()), key=lambda j: -j["created"])


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    if jid not in jobs:
        raise HTTPException(404)
    return jobs[jid]


@app.get("/api/scans")
def list_scans():
    out = []
    for p in sorted(pipeline.SCANS.glob("scan_*.json"), reverse=True):
        try:
            r = json.loads(p.read_text())
            out.append({"file": p.name, "created": r["created"], "days": r["days"], "n": len(r["candidates"])})
        except Exception:
            continue
    return out


@app.get("/api/scans/{name}")
def get_scan(name: str):
    p = pipeline.SCANS / Path(name).name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="application/json")


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")

if __name__ == "__main__":
    # run a fresh scan at start-up if the newest one is older than 12 hours
    scans = sorted(pipeline.SCANS.glob("scan_*.json")) if pipeline.SCANS.exists() else []
    if not scans or time.time() - scans[-1].stat().st_mtime > 12 * 3600:
        _submit(ScanRequest())
    print("Transient Hunter → http://localhost:8003")
    uvicorn.run(app, host="127.0.0.1", port=8003, log_level="warning")

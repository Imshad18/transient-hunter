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
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from hunter import pipeline, share, tns, zenodo

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


# ------------------------------------------------------------------ contribution
class Creds(BaseModel):
    bot_id: str
    bot_name: str
    api_key: str


class Author(BaseModel):
    name: str = ""
    affiliation: str = ""
    email: str = ""
    orcid: str = ""


class TnsCheck(BaseModel):
    scan: str
    oid: str
    creds: Creds
    sandbox: bool = False


class TnsPreview(BaseModel):
    scan: str
    oid: str
    reporter: str
    reporting_groupid: str = "0"
    remarks: str = ""
    kind: str = "discovery"          # or "photometry"
    points: list = []


class TnsSubmit(BaseModel):
    report: dict
    creds: Creds
    sandbox: bool = True


class ZenodoReq(BaseModel):
    author: Author
    token: str
    sandbox: bool = True


class PublishReq(BaseModel):
    id: int
    token: str
    sandbox: bool = True


def _scan(name):
    p = pipeline.SCANS / Path(name).name
    if not p.exists():
        raise HTTPException(404, "Scan not found")
    return json.loads(p.read_text())


def _cand(scan, oid):
    for c in _scan(scan)["candidates"]:
        if c["oid"] == oid:
            return c
    raise HTTPException(404, "Object not in this scan")


@app.get("/api/tns/choices")
def tns_choices():
    return tns.choices()


@app.post("/api/tns/check")
def tns_check(req: TnsCheck):
    c = _cand(req.scan, req.oid)
    try:
        return {"matches": tns.search(c["ra"], c["dec"], req.creds.model_dump(), req.sandbox)}
    except Exception as exc:
        raise HTTPException(502, str(exc))


@app.post("/api/tns/preview")
def tns_preview(req: TnsPreview):
    c = _cand(req.scan, req.oid)
    if req.kind == "photometry":
        if not req.points:
            raise HTTPException(400, "Add at least one measurement")
        return tns.photometry_report(c, req.reporter, req.reporting_groupid, req.points)
    return tns.discovery_report(c, req.reporter, req.reporting_groupid, req.remarks)


@app.post("/api/tns/submit")
def tns_submit(req: TnsSubmit):
    try:
        return tns.submit(req.report, req.creds.model_dump(), req.sandbox)
    except Exception as exc:
        raise HTTPException(502, str(exc))


@app.post("/api/astronote/{scan}/{oid}")
def astronote(scan: str, oid: str, author: Author):
    return {"text": share.astronote(_cand(scan, oid), author.model_dump())}


@app.post("/api/package/{scan}")
def package(scan: str, author: Author):
    data, _ = share.scan_package(_scan(scan), author.model_dump())
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{Path(scan).stem}.zip"'})


@app.post("/api/zenodo/{scan}")
def zenodo_draft(scan: str, req: ZenodoReq):
    sc = _scan(scan)
    data, _ = share.scan_package(sc, req.author.model_dump())
    meta = share.zenodo_metadata(sc, req.author.model_dump(), zenodo.creator(req.author.model_dump()))
    try:
        return zenodo.draft({f"{Path(scan).stem}.zip": data}, meta, req.token, req.sandbox)
    except Exception as exc:
        raise HTTPException(502, str(exc))


@app.post("/api/zenodo-publish")
def zenodo_publish(req: PublishReq):
    try:
        return zenodo.publish(req.id, req.token, req.sandbox)
    except Exception as exc:
        raise HTTPException(502, str(exc))


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")

if __name__ == "__main__":
    # run a fresh scan at start-up if the newest one is older than 12 hours
    scans = sorted(pipeline.SCANS.glob("scan_*.json")) if pipeline.SCANS.exists() else []
    if not scans or time.time() - scans[-1].stat().st_mtime > 12 * 3600:
        _submit(ScanRequest())
    print("Transient Hunter → http://localhost:8003")
    uvicorn.run(app, host="127.0.0.1", port=8003, log_level="warning")

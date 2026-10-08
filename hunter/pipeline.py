"""Scan recent ZTF transients, analyse each light curve, rank for follow-up."""
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from . import alerce
from .analyze import analyze

SCANS = Path(__file__).resolve().parent.parent / "scans"


def _one(item, now):
    oid = item["oid"]
    lc = alerce.lightcurve(oid)
    res = analyze(oid, lc, now)
    if res is None:
        return None
    try:
        probs = alerce.probabilities(oid)
    except Exception:
        probs = []
    top = {}
    for p in probs:
        if p.get("ranking") == 1:
            top[p["classifier_name"]] = {"class": p["class_name"], "prob": round(p["probability"], 3)}
    res.update(ra=item["meanra"], dec=item["meandec"], sn_prob=item["probability"],
               alerce=top.get("lc_classifier") or top.get("lc_classifier_transient"),
               alerce_stamp=top.get("stamp_classifier"))
    return res


def scan(days=14, min_prob=0.4, max_objects=200, progress=None):
    t0 = time.time()
    now = alerce.now_mjd()
    if progress:
        progress(2, f"Querying ALeRCE for supernova-like ZTF alerts first seen in the last {days} days…")
    items = alerce.recent_candidates(days, min_prob, max_objects)
    if progress:
        progress(8, f"{len(items)} candidates. Downloading light curves and fitting…")
    out, failed = [], 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_one, it, now): it for it in items}
        for k, f in enumerate(as_completed(futs)):
            try:
                r = f.result()
                if r:
                    out.append(r)
            except Exception:
                failed += 1
            if progress and k % 10 == 0:
                progress(8 + 90 * (k + 1) / max(1, len(items)), f"Analysed {k + 1}/{len(items)} light curves")
    out.sort(key=lambda r: -r["score"])
    res = {"created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "now_mjd": now, "days": days,
           "min_prob": min_prob, "queried": len(items), "failed": failed, "runtime_s": round(time.time() - t0, 1),
           "candidates": out}
    SCANS.mkdir(exist_ok=True)
    name = f"scan_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.json"
    (SCANS / name).write_text(json.dumps(res))
    res["file"] = name
    if progress:
        progress(100, f"Done: {len(out)} transients analysed in {res['runtime_s']} s")
    return res

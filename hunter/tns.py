"""Transient Name Server (TNS) API: search, object details and AT reports.

Reports are sent by a TNS "bot" that you create on wis-tns.org (free). The sandbox
(sandbox.wis-tns.org) accepts the same calls and is wiped weekly, so test there first.
Format and value ids follow the TNS 2.0 bulk-report manual and /api/get/values.
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

VALUES = json.loads((Path(__file__).with_name("tns_values.json")).read_text())["data"]
ZTF_INSTRUMENT = "196"   # P48 - ZTF-Cam
ZTF_FILTERS = {"g": "110", "r": "111", "i": "112"}
ZTF_GROUP = "48"         # ZTF (discovery data source)
AB_MAG = "1"
PSN = "1"                # at_type: possible supernova


def _base(sandbox):
    return "https://sandbox.wis-tns.org/api" if sandbox else "https://www.wis-tns.org/api"


def _headers(creds):
    marker = 'tns_marker{"tns_id": "%s", "type": "bot", "name": "%s"}' % (creds["bot_id"], creds["bot_name"])
    return {"User-Agent": marker}


def _post(path, creds, sandbox, data=None, **extra):
    r = requests.post(f"{_base(sandbox)}{path}", headers=_headers(creds),
                      data={"api_key": creds["api_key"], **({"data": json.dumps(data)} if data is not None else {}), **extra},
                      timeout=60)
    try:
        body = r.json()
    except ValueError:
        raise RuntimeError(f"TNS returned {r.status_code}: {r.text[:200]}")
    if r.status_code != 200 or body.get("id_code") not in (200, None):
        raise RuntimeError(f"TNS {body.get('id_code', r.status_code)}: {body.get('id_message', '')} {json.dumps(body.get('data', ''))[:300]}")
    return body


def search(ra, dec, creds, sandbox=False, radius=3.0):
    body = _post("/get/search", creds, sandbox, {"ra": f"{ra:.6f}", "dec": f"{dec:.6f}", "radius": str(radius), "units": "arcsec"})
    out = []
    for o in body.get("data") or []:
        try:
            d = _post("/get/object", creds, sandbox, {"objname": o["objname"], "photometry": "0", "spectra": "0"}).get("data", {})
        except Exception:
            d = {}
        out.append({
            "objname": f"{o.get('prefix', 'AT')} {o['objname']}", "objid": o.get("objid"),
            "url": f"https://www.wis-tns.org/object/{o['objname']}",
            "reporting_group": (d.get("reporting_group") or {}).get("group_name"),
            "discoverer": d.get("discoverer"), "discovery_date": d.get("discoverydate"),
            "type": (d.get("object_type") or {}).get("name"), "internal_names": d.get("internal_names"),
        })
    return out


def _sexa(ra, dec):
    h = ra / 15
    hh, mm = int(h), int((h - int(h)) * 60)
    ss = ((h - hh) * 60 - mm) * 60
    sign = "-" if dec < 0 else "+"
    a = abs(dec)
    dd, dm = int(a), int((a - int(a)) * 60)
    ds = ((a - dd) * 60 - dm) * 60
    return f"{hh:02d}:{mm:02d}:{ss:05.2f}", f"{sign}{dd:02d}:{dm:02d}:{ds:04.1f}"


def _date(mjd):
    """TNS accepts 'YYYY-MM-DD HH:MM:SS'."""
    return datetime.fromtimestamp((mjd - 40587) * 86400, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def discovery_report(c, reporter, reporting_groupid="0", remarks=""):
    """AT (discovery) report for a ZTF transient, built from the public alert photometry."""
    ra, dec = _sexa(c["ra"], c["dec"])
    points = sorted(((b, t, m, e) for b, d in c["bands"].items() for t, m, e in zip(d["mjd"], d["mag"], d["err"])), key=lambda x: x[1])
    first = points[0]
    phot = {}
    for k, (b, t, m, e) in enumerate(points[:10]):
        phot[str(k)] = {"obsdate": _date(t), "flux": f"{m:.3f}", "flux_error": f"{e:.3f}", "limiting_flux": "",
                        "flux_unitid": AB_MAG, "filterid": ZTF_FILTERS.get(b, "0"), "instrumentid": ZTF_INSTRUMENT,
                        "exptime": "30", "observer": "Robot", "comments": "ZTF public alert stream"}
    rep = {
        "ra": {"value": ra, "error": "0.5", "units": "arcsec"},
        "dec": {"value": dec, "error": "0.5", "units": "arcsec"},
        "reporting_groupid": str(reporting_groupid), "data_source_groupid": ZTF_GROUP,
        "reporter": reporter, "discovery_datetime": _date(first[1]), "at_type": PSN,
        "internal_name": c["oid"],
        "remarks": remarks or ("Identified in the ZTF public alert stream (via the ALeRCE broker) and selected with "
                               f"Transient Hunter: {c['type_hint']}, latest mag {c['last_mag']:.2f}."),
        "photometry": phot,
    }
    if c.get("last_nondet_mjd"):
        b = next((b for b, d in c["bands"].items() if c["last_nondet_mjd"] in d.get("lim_mjd", [])), "r")
        rep["non_detection"] = {"obsdate": _date(c["last_nondet_mjd"]), "limiting_flux": f"{c['last_nondet_mag']:.2f}",
                                "flux_unitid": AB_MAG, "filterid": ZTF_FILTERS.get(b, "111"), "instrumentid": ZTF_INSTRUMENT,
                                "exptime": "30", "observer": "Robot", "comments": ""}
    else:
        rep["non_detection"] = {"archiveid": "0", "archival_remarks": "No ZTF non-detection in the 10 days before discovery in public alerts."}
    return {"at_report": {"0": rep}}


def photometry_report(c, reporter, reporting_groupid, points, data_source_groupid=None):
    """AT report adding your own follow-up photometry to an existing object."""
    ra, dec = _sexa(c["ra"], c["dec"])
    phot = {}
    for k, p in enumerate(points):
        phot[str(k)] = {"obsdate": p["obsdate"].replace("T", " ")[:19], "flux": f"{float(p['mag']):.3f}",
                        "flux_error": f"{float(p['err']):.3f}" if p.get("err") else "", "limiting_flux": "",
                        "flux_unitid": AB_MAG, "filterid": str(p["filterid"]), "instrumentid": str(p["instrumentid"]),
                        "exptime": str(p.get("exptime") or ""), "observer": p.get("observer") or reporter,
                        "comments": p.get("comments") or ""}
    first = min(points, key=lambda p: p["obsdate"])
    return {"at_report": {"0": {
        "ra": {"value": ra, "error": "1", "units": "arcsec"}, "dec": {"value": dec, "error": "1", "units": "arcsec"},
        "reporting_groupid": str(reporting_groupid), "data_source_groupid": str(data_source_groupid or reporting_groupid),
        "reporter": reporter, "discovery_datetime": first["obsdate"].replace("T", " ")[:19], "at_type": PSN,
        "internal_name": "", "remarks": f"Follow-up photometry of {c['oid']}.", "photometry": phot,
        "non_detection": {"archiveid": "0", "archival_remarks": "Follow-up observation of a known transient."},
    }}}


def submit(report, creds, sandbox=True, wait_s=40):
    """Send a bulk report and wait for TNS to process it."""
    body = _post("/set/bulk-report", creds, sandbox, report)
    rid = body["data"]["report_id"]
    deadline = time.time() + wait_s
    reply = None
    while time.time() < deadline:
        time.sleep(4)
        try:
            reply = _post("/get/bulk-report-reply", creds, sandbox, report_id=str(rid))
            break
        except RuntimeError as exc:
            if "404" in str(exc):  # not processed yet
                continue
            raise
    names = []
    if reply:
        for r in (reply.get("data") or {}).get("feedback", {}).get("at_report", []) or []:
            for v in (r.values() if isinstance(r, dict) else []):
                if isinstance(v, dict) and v.get("objname"):
                    names.append(v["objname"])
    return {"report_id": rid, "reply": reply, "objnames": sorted(set(names)), "sandbox": sandbox}


def choices():
    """Dropdown values for the follow-up photometry form."""
    return {k: sorted(({"id": i, "name": n} for i, n in VALUES[k].items()), key=lambda x: x["name"])
            for k in ("filters", "instruments", "groups")}

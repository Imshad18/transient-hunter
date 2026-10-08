"""ALeRCE broker API (ZTF alert stream)."""
import time

import requests

API = "https://api.alerce.online/ztf/v1"
S = requests.Session()


def _get(path, params=None, tries=3):
    for k in range(tries):
        try:
            r = S.get(f"{API}{path}", params=params, timeout=40)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (k + 1))
                continue
            r.raise_for_status()
        except requests.RequestException:
            if k == tries - 1:
                raise
            time.sleep(1.5 * (k + 1))
    raise RuntimeError(f"ALeRCE request failed: {path}")


def now_mjd():
    return time.time() / 86400.0 + 40587.0


def recent_candidates(days=14, min_prob=0.4, max_objects=200, min_ndet=2):
    """Objects whose image stamps ALeRCE classifies as supernova-like, first seen in the last `days`."""
    out, page = [], 1
    first = int(now_mjd() - days)
    while len(out) < max_objects:
        d = _get("/objects/", {"classifier": "stamp_classifier", "class": "SN", "ranking": 1,
                               "probability": min_prob, "firstmjd": first, "ndet": min_ndet,
                               "page": page, "page_size": 100, "order_by": "probability", "order_mode": "DESC"})
        items = d.get("items", [])
        out += items
        if len(items) < 100:
            break
        page += 1
    return out[:max_objects]


def lightcurve(oid):
    return _get(f"/objects/{oid}/lightcurve")


def probabilities(oid):
    return _get(f"/objects/{oid}/probabilities")

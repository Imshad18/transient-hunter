"""Shareable outputs: scan package for Zenodo, AstroNote text."""
import csv
import io
import json
import zipfile
from datetime import datetime, timezone

REPO_URL = "https://github.com/Imshad18/transient-hunter"


def _mjd_date(m):
    return datetime.fromtimestamp((m - 40587) * 86400, timezone.utc).strftime("%Y-%m-%d %H:%M")


def scan_package(scan, author):
    """Ranked candidate list (CSV + JSON) with a README, for archiving."""
    rows = scan["candidates"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["rank", "ztf_id", "ra_deg", "dec_deg", "score", "first_detection_utc", "age_days", "latest_mag", "peak_mag",
                "trend_mag_per_day", "g_minus_r", "light_curve_hint", "alerce_class", "alerce_prob", "follow_up_reasons"])
    for k, c in enumerate(rows, 1):
        w.writerow([k, c["oid"], f"{c['ra']:.6f}", f"{c['dec']:.6f}", c["score"], _mjd_date(c["first_mjd"]), f"{c['age_days']:.2f}",
                    f"{c['last_mag']:.2f}", f"{c['peak_mag']:.2f}", "" if c["slope"] is None else f"{c['slope']:.3f}",
                    "" if c["color_gr"] is None else f"{c['color_gr']:.2f}", c["type_hint"],
                    (c.get("alerce") or {}).get("class", ""), (c.get("alerce") or {}).get("prob", ""), "; ".join(c["score_reasons"])])
    readme = f"""# Transient follow-up priorities, {scan['created'][:16].replace('T', ' ')} UTC

{len(rows)} transients first detected by the Zwicky Transient Facility within {scan['days']} days of the scan,
selected from the ALeRCE broker (stamp classifier SN probability >= {scan['min_prob']}), with Bazin light-curve
fits, colours, a photometric type hint and a follow-up priority score.

Prepared by {author.get('name') or 'the author'}{(', ' + author['affiliation']) if author.get('affiliation') else ''} with {REPO_URL}.

Files: candidates.csv (ranked list), scan.json (full output including light curves and fits).
Type hints are photometric only; spectroscopic classification is required.
Data: ZTF public alerts via ALeRCE.
"""
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as f:
        f.writestr("README.md", readme)
        f.writestr("candidates.csv", buf.getvalue())
        f.writestr("scan.json", json.dumps(scan))
    return z.getvalue(), readme


def zenodo_metadata(scan, author, creator):
    top = ", ".join(c["oid"] for c in scan["candidates"][:5])
    return {
        "upload_type": "dataset",
        "title": f"ZTF transient follow-up priorities, {scan['created'][:10]}",
        "creators": [creator],
        "description": (f"<p>Ranked list of {len(scan['candidates'])} recent ZTF transients with light-curve fits, colours, "
                        f"photometric type hints and follow-up scores. Top candidates: {top}.</p>"
                        "<p>Data: Zwicky Transient Facility public alerts via the ALeRCE broker.</p>"),
        "keywords": ["supernovae", "transients", "ZTF", "follow-up", "time-domain astronomy"],
        "license": "cc-by-4.0",
        "related_identifiers": [{"identifier": REPO_URL, "relation": "isSupplementedBy", "resource_type": "software"}],
    }


def astronote(c, author, tns_name=None):
    name = tns_name or c["oid"]
    return f"""Title: {name} ({c['oid']}): {c['type_hint']}, {'rising' if c['rising'] else 'fading'} at {c['last_mag']:.1f} mag

Authors: {author.get('name') or '<your name>'}{(' (' + author['affiliation'] + ')') if author.get('affiliation') else ''}

We draw attention to {name} (ZTF internal name {c['oid']}, RA {c['ra']:.5f}, Dec {c['dec']:+.5f}), first detected by ZTF on
{_mjd_date(c['first_mjd'])} UTC{f", {c['first_mjd'] - c['last_nondet_mjd']:.1f} d after a non-detection deeper than {c['last_nondet_mag']:.1f} mag" if c.get('last_nondet_mjd') else ''}.
The latest ZTF magnitude is {c['last_mag']:.2f}{f", changing by {c['slope']:+.3f} mag/day over the last week" if c['slope'] is not None else ''}{f", with g-r = {c['color_gr']:.2f}" if c['color_gr'] is not None else ''}.
A Bazin fit to the public light curve gives {f"a rise time of {c['rise_days']:.1f} d" if c['rise_days'] else 'no peak yet'}.
Its photometric behaviour suggests: {c['type_hint']}.

{"; ".join(c['score_reasons']).capitalize() if c['score_reasons'] else ''}. We encourage spectroscopic classification.

Based on ZTF public alerts distributed by the ALeRCE broker; analysis with {REPO_URL}.
"""

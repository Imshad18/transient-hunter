"""Light-curve analysis of a ZTF transient: Bazin fits, rise/decline, colour, type hint, follow-up score."""
import warnings

import numpy as np
from scipy.optimize import curve_fit

BANDS = {1: "g", 2: "r", 3: "i"}
ZP = 23.9  # AB magnitude of 1 microjansky


def mag_to_flux(m):
    return 10 ** (-0.4 * (np.asarray(m) - ZP))


def flux_to_mag(f):
    return ZP - 2.5 * np.log10(np.maximum(f, 1e-6))


def bazin(t, A, t0, trise, tfall, B):
    """Bazin et al. (2009) supernova light-curve model in flux."""
    return A * np.exp(-(t - t0) / tfall) / (1 + np.exp(-(t - t0) / trise)) + B


def fit_band(t, f, ef):
    if len(t) < 4:
        return None
    i = int(np.argmax(f))
    p0 = [f[i] * 1.5, t[i] - 2, 3.0, 25.0, 0.0]
    lo = [0, t.min() - 60, 0.3, 1.0, -abs(f.max())]
    hi = [f.max() * 50, t.max() + 30, 40.0, 400.0, abs(f.max())]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            p, _ = curve_fit(bazin, t, f, p0=p0, sigma=np.maximum(ef, 1e-3), bounds=(lo, hi), maxfev=4000)
    except Exception:
        return None
    resid = (f - bazin(t, *p)) / np.maximum(ef, 1e-3)
    return {"params": p.tolist(), "chi2_dof": float(np.sum(resid ** 2) / max(1, len(t) - 5))}


def _peak_of(p, t_lo, t_hi):
    tt = np.linspace(t_lo - 30, t_hi + 60, 900)
    ff = bazin(tt, *p)
    k = int(np.argmax(ff))
    return float(tt[k]), float(ff[k])


def analyze(oid, lc, now):
    det = [d for d in lc.get("detections", []) if d.get("magpsf") is not None and d.get("fid") in BANDS]
    det = [d for d in det if str(d.get("isdiffpos", 1)) in ("1", "t", "True", "true")]
    if not det:
        return None
    nondet = [n for n in lc.get("non_detections", []) if n.get("diffmaglim") and n.get("fid") in BANDS]
    t_first = min(d["mjd"] for d in det)
    t_last = max(d["mjd"] for d in det)
    # deepest limit in the 10 days before the first detection: how well is the explosion time pinned down?
    pre = [n for n in nondet if t_first - 10 < n["mjd"] < t_first]
    last_nondet = max(pre, key=lambda n: n["mjd"]) if pre else None

    bands, fits = {}, {}
    for fid, name in BANDS.items():
        rows = sorted((d for d in det if d["fid"] == fid), key=lambda d: d["mjd"])
        if not rows:
            continue
        t = np.array([d["mjd"] for d in rows])
        m = np.array([d["magpsf"] for d in rows])
        em = np.array([d.get("sigmapsf") or 0.1 for d in rows])
        f = mag_to_flux(m)
        ef = f * em * 0.921
        bands[name] = {"mjd": np.round(t, 4).tolist(), "mag": np.round(m, 3).tolist(), "err": np.round(em, 3).tolist(),
                       "lim_mjd": [round(n["mjd"], 4) for n in nondet if n["fid"] == fid and n["mjd"] > t_first - 30],
                       "lim_mag": [round(n["diffmaglim"], 2) for n in nondet if n["fid"] == fid and n["mjd"] > t_first - 30]}
        fit = fit_band(t, f, ef)
        if fit:
            tp, fp = _peak_of(fit["params"], t.min(), t.max())
            grid = np.linspace(t_first - 5, max(now, t_last) + 10, 120)
            fit["curve"] = {"mjd": np.round(grid, 3).tolist(), "mag": np.round(flux_to_mag(bazin(grid, *fit["params"])), 3).tolist()}
            fit["t_peak"], fit["mag_peak"] = tp, float(flux_to_mag(fp))
            fits[name] = fit
        # slope of the last week of data (mag/day, negative = brightening)
        recent = t > t.max() - 7
        slope = float(np.polyfit(t[recent], m[recent], 1)[0]) if recent.sum() >= 2 and np.ptp(t[recent]) > 0.5 else None
        bands[name]["slope"] = slope
        bands[name]["last_mag"] = float(m[-1])
        bands[name]["peak_obs"] = float(m.min())

    # g-r colour from the most recent night with both bands
    color = None
    if "g" in bands and "r" in bands:
        g, r = bands["g"], bands["r"]
        for tg, mg in sorted(zip(g["mjd"], g["mag"]), reverse=True):
            close = [mr for tr, mr in zip(r["mjd"], r["mag"]) if abs(tr - tg) < 1.5]
            if close:
                color = float(mg - close[0])
                break

    last_mag = min((b["last_mag"] for b in bands.values()), default=None)
    peak_mag = min((b["peak_obs"] for b in bands.values()), default=None)
    ref = bands.get("r") or bands.get("g")
    slope = ref.get("slope") if ref else None
    main_fit = fits.get("r") or fits.get("g")
    rise_days = decline = None
    if main_fit and main_fit["t_peak"] <= t_last + 1:  # only once the peak has actually been observed
        rise_days = main_fit["t_peak"] - (last_nondet["mjd"] if last_nondet else t_first)
        tp = main_fit["t_peak"]
        if t_last > tp + 5:
            p = main_fit["params"]
            m1, m2 = flux_to_mag(bazin(tp, *p)), flux_to_mag(bazin(tp + 15, *p))
            decline = float((m2 - m1) / 15)
    age = now - t_first
    rising = slope is not None and slope < -0.02
    past_peak = main_fit is not None and t_last > main_fit["t_peak"] + 2

    hint = type_hint(age, len(det), rise_days, decline, color, rising, past_peak)
    score, reasons = follow_up_score(last_mag, age, rising, color, now - t_last, len(det))
    return {
        "oid": oid, "ndet": len(det), "first_mjd": t_first, "last_mjd": t_last, "age_days": age,
        "since_last_days": now - t_last, "last_nondet_mjd": last_nondet["mjd"] if last_nondet else None,
        "last_nondet_mag": last_nondet["diffmaglim"] if last_nondet else None,
        "last_mag": last_mag, "peak_mag": peak_mag, "slope": slope, "rising": rising, "past_peak": past_peak,
        "color_gr": color, "rise_days": rise_days, "decline_mag_day": decline,
        "type_hint": hint, "score": score, "score_reasons": reasons,
        "bands": bands, "fits": {k: {kk: v for kk, v in f.items() if kk != "params"} for k, f in fits.items()},
        "stamp_candid": next((str(d["candid"]) for d in sorted(det, key=lambda d: d["mjd"]) if d.get("has_stamp")), None),
    }


def type_hint(age, ndet, rise, decline, color, rising, past_peak):
    """Rough photometric hint. Spectroscopy is what actually classifies a transient."""
    if ndet < 3 or age < 2:
        return "Too early to tell"
    if color is not None and color < -0.25 and rising:
        return "Young and hot (early core-collapse SN or TDE)"
    if rise is not None and rise < 6 and decline is not None and decline > 0.1:
        return "Fast transient"
    if rise is not None and rise > 35:
        return "Slow riser (superluminous SN, TDE or AGN flare)"
    if decline is not None and decline < 0.015 and past_peak:
        return "Plateau (SN II-like)"
    if rise is not None and 9 <= rise <= 24 and (color is None or -0.3 < color < 0.6):
        return "SN Ia-like"
    if rising:
        return "Rising transient"
    return "Declining transient"


def follow_up_score(last_mag, age, rising, color, since_last, ndet):
    """How useful a spectrum / more photometry would be now (0-100)."""
    s, why = 0, []
    if last_mag is not None:
        if last_mag < 17.5:
            s += 35; why.append("bright (< 17.5 mag)")
        elif last_mag < 18.5:
            s += 25; why.append("bright enough for small telescopes")
        elif last_mag < 19.5:
            s += 12
    if age < 3:
        s += 25; why.append("discovered < 3 days ago")
    elif age < 7:
        s += 15; why.append("discovered this week")
    elif age < 14:
        s += 5
    if rising:
        s += 20; why.append("still rising")
    if color is not None and color < -0.1:
        s += 8; why.append("blue colour")
    if since_last > 5:
        s -= 15; why.append("no detection for 5+ days")
    if ndet >= 5:
        s += 5
    return int(max(0, min(100, s))), why

# services/mlb_espn_scoreboard.py
from __future__ import annotations

from typing import Any, Dict, List, Optional
import requests

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/summary"

def mlb_game_url(event_id: str | None) -> str:
    if not event_id:
        return ""
    return f"https://www.espn.com/mlb/game/_/gameId/{event_id}"

def _safe_int(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        if isinstance(x, str) and x.strip() == "":
            return None
        return int(float(x))
    except Exception:
        return None


def _find_probables_in_obj(obj: Any) -> Dict[str, Optional[Dict[str, Any]]]:
    """Recursively search a JSON-like object for probable/probables entries.

    Returns a dict with optional 'home' and 'away' entries like {"home": {id,name}, "away": ...}
    """
    out = {"home": None, "away": None}

    def _extract_probable(athlete_like: Any) -> Optional[Dict[str, Any]]:
        if athlete_like is None:
            return None
        if isinstance(athlete_like, dict):
            name = (
                athlete_like.get("displayName")
                or athlete_like.get("fullName")
                or athlete_like.get("shortName")
                or athlete_like.get("name")
            )
            pid = athlete_like.get("id") or athlete_like.get("playerId")
            return {"id": pid, "name": name} if (name or pid) else None
        s = str(athlete_like).strip()
        return {"id": None, "name": s} if s else None

    def _recurse(o: Any, side_ctx: Optional[str] = None) -> None:
        if o is None:
            return
        if isinstance(o, dict):
            next_side_ctx = side_ctx
            o_side = o.get("homeAway") or o.get("homeaway")
            if o_side in ("home", "away"):
                next_side_ctx = o_side

            for k, v in o.items():
                if not k:
                    continue
                key = str(k).lower()
                if key in ("probablepitcher", "probable", "probables", "probablepitchers", "projectedpitcher"):
                    # v can be a dict or list
                    if isinstance(v, dict):
                        side = (v.get("homeAway") or v.get("homeaway") or next_side_ctx)
                        athlete = v.get("athlete") or v.get("player") or v
                        parsed = _extract_probable(athlete)
                        if side == "home" and not out["home"] and parsed:
                            out["home"] = parsed
                        if side == "away" and not out["away"] and parsed:
                            out["away"] = parsed

                    elif isinstance(v, list):
                        for item in v:
                            if not isinstance(item, dict):
                                continue
                            side = item.get("homeAway") or item.get("homeaway") or next_side_ctx
                            athlete = item.get("athlete") or item.get("player") or item
                            parsed = _extract_probable(athlete)

                            if side == "home" and not out["home"] and parsed:
                                out["home"] = parsed
                            if side == "away" and not out["away"] and parsed:
                                out["away"] = parsed

                # continue searching deeper
                _recurse(v, next_side_ctx)
        elif isinstance(o, list):
            for i in o:
                _recurse(i, side_ctx)

    _recurse(obj)
    return out


def _fetch_probables_for_event(event_id: str, timeout: int = 12) -> Optional[Dict[str, Optional[Dict[str, Any]]]]:
    """Best-effort fetch of extra event details to find probable pitchers.

    Returns a dict like {"home": {id,name}, "away": {id,name}} or None on failure.
    """
    try:
        r = requests.get(SUMMARY_URL, params={"event": event_id}, timeout=timeout, headers={"User-Agent": "cbb-dashboard/1.0"})
        r.raise_for_status()
        j = r.json()
        found = _find_probables_in_obj(j)
        # return only if something found
        if found.get("home") or found.get("away"):
            return found
    except Exception:
        return None
    return None

def get_mlb_games(date_yyyymmdd: str, timeout: int = 12, use_summary_fallback: bool = True) -> List[Dict[str, Any]]:
    """
    date_yyyymmdd: '20260113'
    Returns a list of games with teams + status + (final/live) scores when present.
    """
    r = requests.get(
        SCOREBOARD_URL,
        params={"dates": date_yyyymmdd},
        timeout=timeout,
        headers={"User-Agent": "cbb-dashboard/1.0"},
    )
    r.raise_for_status()
    data = r.json()

    out: List[Dict[str, Any]] = []
    # First pass: parse scoreboard JSON and collect events needing summary fallback
    need_summary: Dict[int, str] = {}
    for ev_idx, ev in enumerate(data.get("events", []) or []):
        event_id = ev.get("id")
        competitions = ev.get("competitions") or []
        if not competitions:
            continue
        comp = competitions[0]

        status = (comp.get("status") or {})
        st_type = (status.get("type") or {})
        state = st_type.get("state")  # "pre", "in", "post"
        detail = st_type.get("detail") or st_type.get("description") or ""

        # Teams + scores
        home = away = None
        home_probable = None
        away_probable = None
        competitors = comp.get("competitors", []) or []
        for c in competitors:
            side = c.get("homeAway")
            team = c.get("team") or {}
            item = {
                "id": team.get("id"),
                "abbr": team.get("abbreviation"),
                "name": team.get("displayName"),
                "score": None if state == "pre" else _safe_int(c.get("score")),
            }
            if side == "home":
                home = item
            elif side == "away":
                away = item

            # ESPN commonly stores SP info in competitor.probables[]
            if side in ("home", "away"):
                c_probables = c.get("probables") or []
                for p in c_probables:
                    if not isinstance(p, dict):
                        continue
                    athlete = p.get("athlete") or p.get("player") or p
                    if isinstance(athlete, dict):
                        pname = (
                            athlete.get("displayName")
                            or athlete.get("fullName")
                            or athlete.get("shortName")
                            or athlete.get("name")
                        )
                        pid = athlete.get("id") or p.get("playerId")
                    else:
                        pname = str(athlete).strip()
                        pid = p.get("playerId")

                    parsed = {"id": pid, "name": pname} if (pname or pid) else None
                    if side == "home" and not home_probable and parsed:
                        home_probable = parsed
                    if side == "away" and not away_probable and parsed:
                        away_probable = parsed

        # Probable / projected starting pitchers (ESPN sometimes exposes a comp-level 'probables' list)
        probables = comp.get("probables") or comp.get("probablePitchers") or []
        for p in (probables or []):
            try:
                p_side = p.get("homeAway")
                athlete = p.get("athlete") or p.get("player") or {}
                pname = athlete.get("displayName") or athlete.get("fullName") or athlete.get("shortName") or athlete.get("name")
                pid = athlete.get("id") or p.get("playerId")
            except Exception:
                p_side = None
                pname = None
                pid = None

            if p_side == "home" and not home_probable:
                home_probable = {"id": pid, "name": pname} if (pname or pid) else None
            elif p_side == "away" and not away_probable:
                away_probable = {"id": pid, "name": pname} if (pname or pid) else None

        # Some ESPN variants place the probable pitcher on the competitor object itself
        for c in competitors:
            side = c.get("homeAway")
            pp = c.get("probablePitcher") or c.get("probable")
            if pp and isinstance(pp, dict):
                athlete = pp.get("athlete") or pp.get("player") or pp
                pname = None
                pid = None
                if isinstance(athlete, dict):
                    pname = athlete.get("displayName") or athlete.get("fullName") or athlete.get("name")
                    pid = athlete.get("id")
                else:
                    pname = str(athlete)

                if side == "home" and not home_probable:
                    home_probable = {"id": pid, "name": pname} if (pname or pid) else None
                if side == "away" and not away_probable:
                    away_probable = {"id": pid, "name": pname} if (pname or pid) else None

        # Defer summary lookups to a batched/parallel step to avoid serial network requests
        if state == "pre" and use_summary_fallback and (not home_probable or not away_probable) and event_id:
            need_summary[len(out)] = str(event_id)

        # If still missing probables for a pregame, we'll fill TBA later after any fallback

        # Start time
        start_time = comp.get("date")  # ISO string

        out.append({
            "id": event_id,
            "url": mlb_game_url(str(event_id) if event_id is not None else None),
            "startTime": start_time,
            "state": state,          # pre / in / post
            "status": detail,        # "Final", "Scheduled", etc.
            "home": home,
            "away": away,
            "home_probable": home_probable,
            "away_probable": away_probable,
        })

    # If we need to enrich some events with summary lookups, do that in parallel
    if use_summary_fallback and need_summary:
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def _fetch_wrap(idx, eid):
                try:
                    return idx, _fetch_probables_for_event(eid, timeout=timeout)
                except Exception:
                    return idx, None

            max_workers = min(8, max(2, len(need_summary)))
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = [ex.submit(_fetch_wrap, idx, eid) for idx, eid in need_summary.items()]
                for f in as_completed(futures):
                    try:
                        idx, fb = f.result()
                    except Exception:
                        continue
                    if not fb:
                        continue
                    # Only set values if they were missing originally
                    cur = out[idx]
                    if not cur.get("home_probable") and fb.get("home"):
                        cur["home_probable"] = fb.get("home")
                    if not cur.get("away_probable") and fb.get("away"):
                        cur["away_probable"] = fb.get("away")
        except Exception:
            # Non-fatal: continue with whatever we have
            pass

    # Final pass: ensure pregame games always have some probable placeholder
    for cur in out:
        if cur.get("state") == "pre":
            if not cur.get("home_probable"):
                cur["home_probable"] = {"id": None, "name": "TBA"}
            if not cur.get("away_probable"):
                cur["away_probable"] = {"id": None, "name": "TBA"}

    return out

from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests
from fastapi import HTTPException

PGA_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard"
REQUEST_HEADERS = {"User-Agent": "sports-slate/1.0"}


def _score_to_int(score: Any) -> Optional[int]:
    if score is None:
        return None

    if isinstance(score, (int, float)):
        return int(score)

    if not isinstance(score, str):
        return None

    text = score.strip().upper()
    if not text:
        return None
    if text == "E":
        return 0

    try:
        return int(float(text))
    except Exception:
        return None


def _score_display(score: Any) -> str:
    if score is None:
        return ""

    if isinstance(score, str):
        text = score.strip()
        if text:
            return text
        return ""

    try:
        n = int(float(score))
    except Exception:
        return str(score)

    if n > 0:
        return f"+{n}"
    if n == 0:
        return "E"
    return str(n)


def _holes_completed(competitor: Dict[str, Any]) -> Optional[int]:
    linescores = competitor.get("linescores") or []
    if not linescores:
        return None

    first_round = linescores[0] if isinstance(linescores[0], dict) else None
    if not first_round:
        return None

    round_holes = first_round.get("linescores") or []
    return len(round_holes) if isinstance(round_holes, list) else None


def _parse_tee_time_from_competitor(comp: Dict[str, Any]) -> Optional[str]:
    # ESPN includes competitor-aggregates with advertised tee time strings in statistics entries.
    # Look for a timestamp-like string (e.g., "Thu Apr 02 10:12:00 PDT 2026").
    for ls in (comp.get("linescores") or []):
        if not isinstance(ls, dict):
            continue
        stats = ls.get("statistics") or {}
        categories = stats.get("categories") or []
        for category in categories:
            for stat in category.get("stats") or []:
                display = stat.get("displayValue")
                if isinstance(display, str) and display.strip():
                    if any(token in display for token in ["AM", "PM", "PDT", "EDT", "CST", "UTC"]):
                        return display.strip()
    return None


def _tee_time_sort_key(tee_time: Optional[str]) -> int:
    """Extract hour and minute from tee_time string for sorting.
    Returns minutes since midnight, or large number if unparseable."""
    if not tee_time or not isinstance(tee_time, str):
        return 999999
    
    # Format: "Thu Apr 02 16:36:00 EDT 2026"
    parts = tee_time.strip().split()
    if len(parts) >= 4:
        time_str = parts[3]  # "16:36:00"
        time_parts = time_str.split(":")
        if len(time_parts) >= 2:
            try:
                hour = int(time_parts[0])
                minute = int(time_parts[1])
                return hour * 60 + minute
            except Exception:
                pass
    
    return 999999


def _normalize_leaderboard_rows(competitors: List[Dict[str, Any]], default_tee_time: Optional[str] = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for comp in competitors:
        athlete = comp.get("athlete") or {}
        score_raw = comp.get("score")
        score_num = _score_to_int(score_raw)
        round_strokes = {}
        round_to_par = {}
        linescores = comp.get("linescores") or []
        for rs in linescores:
            if not isinstance(rs, dict):
                continue
            round_num = rs.get("period")
            if round_num is None:
                continue
            try:
                round_num = int(round_num)
            except Exception:
                continue

            stroke_value = rs.get("value")
            if stroke_value is not None:
                round_strokes[round_num] = int(stroke_value) if isinstance(stroke_value, (int, float)) and float(stroke_value).is_integer() else stroke_value

            to_par_value = rs.get("displayValue")
            if to_par_value is not None:
                round_to_par[round_num] = str(to_par_value)

        tee_time = _parse_tee_time_from_competitor(comp) or default_tee_time
        row = {
            "order": comp.get("order"),
            "player": {
                "id": athlete.get("id"),
                "name": athlete.get("displayName") or athlete.get("fullName") or athlete.get("shortName") or "Unknown",
                "short_name": athlete.get("shortName"),
                "country": ((athlete.get("flag") or {}).get("alt")),
                "country_flag": ((athlete.get("flag") or {}).get("href")),
            },
            "score": {
                "raw": score_raw,
                "display": _score_display(score_raw),
                "to_par": score_num,
            },
            "holes_completed": _holes_completed(comp),
            "round_strokes": round_strokes,
            "round_to_par": round_to_par,
            "tee_time": tee_time,
        }
        row["not_started"] = (row["holes_completed"] == 0)
        rows.append(row)

    # Sort: started by score, not-started by tee time (soonest first)
    def sort_key(r):
        is_not_started = r.get("not_started", False)
        if is_not_started:
            # Not-started: sort by tee time (earliest first), then by name
            return (True, _tee_time_sort_key(r.get("tee_time")), r["player"].get("name") or "")
        else:
            # Started: sort by score, then by name
            return (False, r["score"]["to_par"] if r["score"]["to_par"] is not None else 999, r["player"].get("name") or "")
    
    rows.sort(key=sort_key)

    rank = 0
    prev_score = object()
    for idx, row in enumerate(rows, start=1):
        cur = row["score"]["to_par"]
        if cur != prev_score:
            rank = idx
            prev_score = cur
        row["position"] = rank if not row.get("not_started") else None

    return rows


def get_pga_leaderboard(date_yyyymmdd: Optional[str] = None, limit: int = 50, timeout: int = 15) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    if date_yyyymmdd:
        params["dates"] = date_yyyymmdd

    try:
        response = requests.get(PGA_SCOREBOARD_URL, params=params, timeout=timeout, headers=REQUEST_HEADERS)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ESPN request failed: {type(e).__name__}: {e}")

    if response.status_code != 200:
        raise HTTPException(
            status_code=500,
            detail={
                "source": "espn",
                "requested_url": response.url,
                "status_code": response.status_code,
                "body_preview": response.text[:800],
            },
        )

    data = response.json()
    events = data.get("events") or []
    if not events:
        return {
            "date": date_yyyymmdd,
            "event": None,
            "count": 0,
            "leaderboard": [],
            "source": PGA_SCOREBOARD_URL,
        }

    event = events[0]
    competition = (event.get("competitions") or [{}])[0]
    status = (competition.get("status") or {}).get("type") or {}

    competitors = competition.get("competitors") or []
    competition_time = competition.get("date") or event.get("date")
    leaderboard = _normalize_leaderboard_rows(competitors, competition_time)
    total_count = len(leaderboard)

    if limit > 0:
        leaderboard = leaderboard[:limit]
    
    # Detect tournament timezone from event name or default to EDT (most PGA tournaments are in EDT)
    event_name = (event.get("name") or "").upper()
    tournament_tz = "EDT"  # Default to EDT
    # Hardcode common tournament locations
    if "HAWAII" in event_name or "KAPALUA" in event_name:
        tournament_tz = "HST"
    elif "LOS ANGELES" in event_name or "CALIFORNIA" in event_name:
        tournament_tz = "PST"

    return {
        "date": date_yyyymmdd,
        "event": {
            "id": event.get("id"),
            "name": event.get("name"),
            "short_name": event.get("shortName"),
            "start_date": competition.get("date") or event.get("date"),
            "end_date": competition.get("endDate") or event.get("endDate"),
            "status": {
                "state": status.get("state"),
                "description": status.get("description"),
                "detail": status.get("detail"),
                "completed": status.get("completed"),
            },
            "tournament_timezone": tournament_tz,
        },
        "count": len(leaderboard),
        "total_count": total_count,
        "leaderboard": leaderboard,
        "source": PGA_SCOREBOARD_URL,
    }
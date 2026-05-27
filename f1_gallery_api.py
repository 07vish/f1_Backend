"""
F1 Gallery Backend - FastAPI starter
===================================

Purpose:
- One backend for your Flutter F1 Gallery app.
- Uses Jolpica for schedule/standings/results.
- Uses OpenF1 for sessions, drivers, live-ish timing, weather, laps, positions.
- Optional FastF1 analytics endpoints for telemetry/lap data.

Run:
    pip install fastapi uvicorn httpx pydantic fastf1 pandas
    uvicorn f1_gallery_api:app --reload --host 0.0.0.0 --port 8000

Test:
    http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


# =============================
# CONFIG
# =============================

OPENF1_BASE_URL = "https://api.openf1.org/v1"
JOLPICA_BASE_URL = "https://api.jolpi.ca/ergast/f1"

# OpenF1 historical endpoints usually work without auth.
# If you later buy/use real-time access, put token in env:
# Windows PowerShell:
#   setx OPENF1_TOKEN "your_token"
OPENF1_TOKEN = os.getenv("OPENF1_TOKEN")

CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "60"))
FASTF1_CACHE_DIR = Path(os.getenv("FASTF1_CACHE_DIR", ".fastf1_cache"))


# =============================
# APP INIT
# =============================

app = FastAPI(
    title="F1 Gallery API",
    description="Backend API for Flutter F1 Gallery app using Jolpica, OpenF1, and optional FastF1 analytics.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For dev. In production, replace with your Flutter web/app domain.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================
# SIMPLE IN-MEMORY CACHE
# =============================

_cache: Dict[str, Dict[str, Any]] = {}


def cache_get(key: str) -> Optional[Any]:
    item = _cache.get(key)
    if not item:
        return None

    if time.time() - item["created_at"] > CACHE_TTL_SECONDS:
        _cache.pop(key, None)
        return None

    return item["data"]


def cache_set(key: str, data: Any) -> Any:
    _cache[key] = {
        "created_at": time.time(),
        "data": data,
    }
    return data


# =============================
# HTTP HELPERS
# =============================

async def fetch_json(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    use_openf1_auth: bool = False,
    cache_key: Optional[str] = None,
) -> Any:
    final_cache_key = cache_key or f"{url}:{params}"

    cached = cache_get(final_cache_key)
    if cached is not None:
        return cached

    headers = {}
    if use_openf1_auth and OPENF1_TOKEN:
        headers["Authorization"] = f"Bearer {OPENF1_TOKEN}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            return cache_set(final_cache_key, data)

    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail={
                "message": "External F1 API returned an error.",
                "url": str(e.request.url),
                "error": e.response.text[:500],
            },
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Could not connect to external F1 API.",
                "error": str(e),
            },
        )


# =============================
# MODELS
# =============================

class HealthResponse(BaseModel):
    status: str
    app: str
    version: str


# =============================
# ROOT
# =============================

@app.get("/", response_model=HealthResponse)
async def root():
    return HealthResponse(
        status="running",
        app="F1 Gallery API",
        version="1.0.0",
    )


@app.get("/health")
async def health():
    return {
        "ok": True,
        "openf1": OPENF1_BASE_URL,
        "jolpica": JOLPICA_BASE_URL,
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
    }


# =============================
# JOLPICA / ERGAST-STYLE ENDPOINTS
# Good for Flutter screens:
# calendar, drivers, constructors, standings, results.
# =============================

@app.get("/calendar/{season}")
async def get_calendar(season: str = "current"):
    """
    Race calendar for a season.
    Example:
        /calendar/current
        /calendar/2024
    """
    url = f"{JOLPICA_BASE_URL}/{season}.json"
    data = await fetch_json(url, cache_key=f"calendar:{season}")
    races = data.get("MRData", {}).get("RaceTable", {}).get("Races", [])

    return {
        "season": season,
        "count": len(races),
        "races": races,
    }


@app.get("/standings/drivers/{season}")
async def get_driver_standings(season: str = "current"):
    url = f"{JOLPICA_BASE_URL}/{season}/driverStandings.json"
    data = await fetch_json(url, cache_key=f"driver_standings:{season}")

    lists = data.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists", [])
    standings = lists[0].get("DriverStandings", []) if lists else []

    return {
        "season": season,
        "count": len(standings),
        "standings": standings,
    }


@app.get("/standings/constructors/{season}")
async def get_constructor_standings(season: str = "current"):
    url = f"{JOLPICA_BASE_URL}/{season}/constructorStandings.json"
    data = await fetch_json(url, cache_key=f"constructor_standings:{season}")

    lists = data.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists", [])
    standings = lists[0].get("ConstructorStandings", []) if lists else []

    return {
        "season": season,
        "count": len(standings),
        "standings": standings,
    }


@app.get("/drivers/{season}")
async def get_drivers(season: str = "current"):
    url = f"{JOLPICA_BASE_URL}/{season}/drivers.json"
    data = await fetch_json(url, cache_key=f"drivers:{season}")

    drivers = data.get("MRData", {}).get("DriverTable", {}).get("Drivers", [])

    return {
        "season": season,
        "count": len(drivers),
        "drivers": drivers,
    }


@app.get("/constructors/{season}")
async def get_constructors(season: str = "current"):
    url = f"{JOLPICA_BASE_URL}/{season}/constructors.json"
    data = await fetch_json(url, cache_key=f"constructors:{season}")

    constructors = data.get("MRData", {}).get("ConstructorTable", {}).get("Constructors", [])

    return {
        "season": season,
        "count": len(constructors),
        "constructors": constructors,
    }


@app.get("/race/{season}/{round_no}/results")
async def get_race_results(season: str, round_no: int):
    url = f"{JOLPICA_BASE_URL}/{season}/{round_no}/results.json"
    data = await fetch_json(url, cache_key=f"race_results:{season}:{round_no}")

    races = data.get("MRData", {}).get("RaceTable", {}).get("Races", [])

    return {
        "season": season,
        "round": round_no,
        "race": races[0] if races else None,
    }


@app.get("/race/{season}/{round_no}/qualifying")
async def get_qualifying_results(season: str, round_no: int):
    url = f"{JOLPICA_BASE_URL}/{season}/{round_no}/qualifying.json"
    data = await fetch_json(url, cache_key=f"qualifying:{season}:{round_no}")

    races = data.get("MRData", {}).get("RaceTable", {}).get("Races", [])

    return {
        "season": season,
        "round": round_no,
        "race": races[0] if races else None,
    }


# =============================
# OPENF1 ENDPOINTS
# Good for live-ish/historical session data:
# meetings, sessions, drivers, positions, intervals, laps, stints, weather, race control.
# =============================

@app.get("/openf1/meetings")
async def openf1_meetings(
    year: Optional[int] = Query(default=None, description="Example: 2024"),
    country_name: Optional[str] = Query(default=None, description="Example: Great Britain"),
):
    params = {}
    if year:
        params["year"] = year
    if country_name:
        params["country_name"] = country_name

    return await fetch_json(
        f"{OPENF1_BASE_URL}/meetings",
        params=params,
        use_openf1_auth=True,
        cache_key=f"openf1:meetings:{params}",
    )


@app.get("/openf1/sessions")
async def openf1_sessions(
    year: Optional[int] = None,
    meeting_key: Optional[int] = None,
    session_name: Optional[str] = Query(default=None, description="Race, Qualifying, Practice 1, Sprint"),
):
    params = {}
    if year:
        params["year"] = year
    if meeting_key:
        params["meeting_key"] = meeting_key
    if session_name:
        params["session_name"] = session_name

    return await fetch_json(
        f"{OPENF1_BASE_URL}/sessions",
        params=params,
        use_openf1_auth=True,
        cache_key=f"openf1:sessions:{params}",
    )


@app.get("/openf1/drivers")
async def openf1_drivers(
    session_key: int = Query(..., description="OpenF1 session_key"),
):
    return await fetch_json(
        f"{OPENF1_BASE_URL}/drivers",
        params={"session_key": session_key},
        use_openf1_auth=True,
        cache_key=f"openf1:drivers:{session_key}",
    )


@app.get("/openf1/positions")
async def openf1_positions(
    session_key: int,
    driver_number: Optional[int] = None,
):
    params = {"session_key": session_key}
    if driver_number:
        params["driver_number"] = driver_number

    return await fetch_json(
        f"{OPENF1_BASE_URL}/position",
        params=params,
        use_openf1_auth=True,
        cache_key=f"openf1:positions:{params}",
    )


@app.get("/openf1/latest-positions")
async def openf1_latest_positions(session_key: int):
    """
    Returns latest known position per driver.
    Useful for Flutter live leaderboard card.
    """
    positions = await fetch_json(
        f"{OPENF1_BASE_URL}/position",
        params={"session_key": session_key},
        use_openf1_auth=True,
        cache_key=f"openf1:latest_positions_raw:{session_key}",
    )

    latest_by_driver: Dict[int, Dict[str, Any]] = {}

    for row in positions:
        driver_no = row.get("driver_number")
        if driver_no is None:
            continue

        old = latest_by_driver.get(driver_no)
        if old is None or str(row.get("date", "")) > str(old.get("date", "")):
            latest_by_driver[driver_no] = row

    sorted_positions = sorted(
        latest_by_driver.values(),
        key=lambda x: x.get("position", 999),
    )

    return {
        "session_key": session_key,
        "count": len(sorted_positions),
        "positions": sorted_positions,
    }


@app.get("/openf1/intervals")
async def openf1_intervals(
    session_key: int,
    driver_number: Optional[int] = None,
):
    params = {"session_key": session_key}
    if driver_number:
        params["driver_number"] = driver_number

    return await fetch_json(
        f"{OPENF1_BASE_URL}/intervals",
        params=params,
        use_openf1_auth=True,
        cache_key=f"openf1:intervals:{params}",
    )


@app.get("/openf1/laps")
async def openf1_laps(
    session_key: int,
    driver_number: Optional[int] = None,
):
    params = {"session_key": session_key}
    if driver_number:
        params["driver_number"] = driver_number

    return await fetch_json(
        f"{OPENF1_BASE_URL}/laps",
        params=params,
        use_openf1_auth=True,
        cache_key=f"openf1:laps:{params}",
    )


@app.get("/openf1/stints")
async def openf1_stints(
    session_key: int,
    driver_number: Optional[int] = None,
):
    params = {"session_key": session_key}
    if driver_number:
        params["driver_number"] = driver_number

    return await fetch_json(
        f"{OPENF1_BASE_URL}/stints",
        params=params,
        use_openf1_auth=True,
        cache_key=f"openf1:stints:{params}",
    )


@app.get("/openf1/weather")
async def openf1_weather(session_key: int):
    return await fetch_json(
        f"{OPENF1_BASE_URL}/weather",
        params={"session_key": session_key},
        use_openf1_auth=True,
        cache_key=f"openf1:weather:{session_key}",
    )


@app.get("/openf1/race-control")
async def openf1_race_control(session_key: int):
    return await fetch_json(
        f"{OPENF1_BASE_URL}/race_control",
        params={"session_key": session_key},
        use_openf1_auth=True,
        cache_key=f"openf1:race_control:{session_key}",
    )


@app.get("/openf1/car-data")
async def openf1_car_data(
    session_key: int,
    driver_number: int,
    limit: int = Query(default=300, ge=1, le=2000),
):
    """
    Car telemetry can be huge. This returns only last N records.
    """
    data = await fetch_json(
        f"{OPENF1_BASE_URL}/car_data",
        params={
            "session_key": session_key,
            "driver_number": driver_number,
        },
        use_openf1_auth=True,
        cache_key=f"openf1:car_data:{session_key}:{driver_number}",
    )

    return {
        "session_key": session_key,
        "driver_number": driver_number,
        "count": min(len(data), limit),
        "data": data[-limit:],
    }


# =============================
# COMBINED DASHBOARD ENDPOINTS
# These are what Flutter should mostly call.
# Less work for UI, less madness for you.
# =============================

@app.get("/dashboard")
async def dashboard(season: str = "current"):
    """
    One endpoint for Home screen:
    - Calendar
    - Driver standings
    - Constructor standings
    """
    calendar = await get_calendar(season)
    driver_standings = await get_driver_standings(season)
    constructor_standings = await get_constructor_standings(season)

    races = calendar.get("races", [])

    return {
        "season": season,
        "next_or_current_race": races[-1] if races else None,
        "calendar_count": calendar.get("count", 0),
        "top_drivers": driver_standings.get("standings", [])[:5],
        "top_constructors": constructor_standings.get("standings", [])[:5],
    }


@app.get("/race-weekend/{year}/{meeting_key}")
async def race_weekend(year: int, meeting_key: int):
    """
    Combined race weekend data from OpenF1.
    Use this for race details page.
    """
    sessions = await openf1_sessions(year=year, meeting_key=meeting_key)
    meeting = await openf1_meetings(year=year)

    selected_meeting = None
    for item in meeting:
        if item.get("meeting_key") == meeting_key:
            selected_meeting = item
            break

    return {
        "year": year,
        "meeting": selected_meeting,
        "sessions": sessions,
    }


@app.get("/live-card/{session_key}")
async def live_card(session_key: int):
    """
    One endpoint for your big Home live card.
    """
    drivers = await openf1_drivers(session_key)
    latest_positions = await openf1_latest_positions(session_key)
    weather = await openf1_weather(session_key)

    latest_weather = weather[-1] if weather else None

    driver_map = {
        d.get("driver_number"): d
        for d in drivers
    }

    positions_with_driver = []

    for pos in latest_positions.get("positions", []):
        driver_no = pos.get("driver_number")
        positions_with_driver.append({
            **pos,
            "driver": driver_map.get(driver_no),
        })

    return {
        "session_key": session_key,
        "weather": latest_weather,
        "positions": positions_with_driver,
    }


# =============================
# FASTF1 OPTIONAL ANALYTICS
# Great for premium app features.
# Use carefully because it is heavier than REST APIs.
# =============================

def enable_fastf1():
    try:
        import fastf1
        FASTF1_CACHE_DIR.mkdir(exist_ok=True)
        fastf1.Cache.enable_cache(str(FASTF1_CACHE_DIR))
        return fastf1
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"FastF1 is not available or cache could not be enabled: {e}",
        )


@app.get("/analytics/session-results")
def fastf1_session_results(
    year: int,
    gp: str = Query(..., description="Example: Silverstone, Monza, Bahrain"),
    session: str = Query(default="R", description="FP1, FP2, FP3, Q, S, SQ, R"),
):
    """
    Returns FastF1 session results in simple JSON.
    Heavy endpoint, cache helps.
    """
    fastf1 = enable_fastf1()

    try:
        s = fastf1.get_session(year, gp, session)
        s.load()
        results = s.results

        return {
            "year": year,
            "gp": gp,
            "session": session,
            "count": len(results),
            "results": results.fillna("").to_dict(orient="records"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/analytics/driver-laps")
def fastf1_driver_laps(
    year: int,
    gp: str,
    session: str = "R",
    driver: str = Query(..., description="Driver abbreviation, example: VER, NOR, LEC"),
):
    """
    Returns lap data for one driver.
    Useful for lap chart in Flutter.
    """
    fastf1 = enable_fastf1()

    try:
        s = fastf1.get_session(year, gp, session)
        s.load(laps=True, telemetry=False, weather=False)

        laps = s.laps.pick_drivers(driver)

        columns = [
            "Driver",
            "LapNumber",
            "LapTime",
            "Sector1Time",
            "Sector2Time",
            "Sector3Time",
            "Compound",
            "TyreLife",
            "Stint",
            "PitOutTime",
            "PitInTime",
        ]

        available_columns = [c for c in columns if c in laps.columns]
        clean = laps[available_columns].copy()

        # Convert timedelta values to readable strings.
        for col in clean.columns:
            clean[col] = clean[col].astype(str)

        return {
            "year": year,
            "gp": gp,
            "session": session,
            "driver": driver,
            "count": len(clean),
            "laps": clean.to_dict(orient="records"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/analytics/fastest-lap-telemetry")
def fastf1_fastest_lap_telemetry(
    year: int,
    gp: str,
    session: str = "R",
    driver: str = Query(..., description="Driver abbreviation, example: VER, NOR, LEC"),
):
    """
    Returns telemetry for driver's fastest lap:
    speed, throttle, brake, gear, rpm, distance.
    Good for charts.
    """
    fastf1 = enable_fastf1()

    try:
        s = fastf1.get_session(year, gp, session)
        s.load(laps=True, telemetry=True, weather=False)

        fastest_lap = s.laps.pick_drivers(driver).pick_fastest()
        tel = fastest_lap.get_car_data().add_distance()

        columns = [
            "Date",
            "RPM",
            "Speed",
            "nGear",
            "Throttle",
            "Brake",
            "DRS",
            "Distance",
        ]

        available_columns = [c for c in columns if c in tel.columns]
        clean = tel[available_columns].copy()

        for col in clean.columns:
            clean[col] = clean[col].astype(str)

        return {
            "year": year,
            "gp": gp,
            "session": session,
            "driver": driver,
            "lap_number": str(fastest_lap.get("LapNumber", "")),
            "lap_time": str(fastest_lap.get("LapTime", "")),
            "count": len(clean),
            "telemetry": clean.to_dict(orient="records"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================
# LOCAL DEV ENTRY
# =============================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "f1_gallery_api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )

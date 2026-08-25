#!/usr/bin/env python3
"""KMA village forecast client and deterministic V18 rainfall aggregation helpers."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
import json
import math
import os
from pathlib import Path
import re
import time as time_module
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
KST = ZoneInfo("Asia/Seoul")


def atomic_write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_env_value(name: str, env_path: Path = ENV_PATH) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            clean = line.strip()
            if not clean or clean.startswith("#") or "=" not in clean:
                continue
            key, raw = clean.split("=", 1)
            if key.strip() == name:
                return raw.strip().strip("\"'")
    raise RuntimeError(f"{name} is not configured")


def latlon_to_grid(latitude: float, longitude: float) -> tuple[int, int]:
    """Convert WGS84 coordinates to KMA's 5 km Lambert grid."""
    earth_radius_km = 6371.00877
    grid_km = 5.0
    standard_lat_1 = 30.0
    standard_lat_2 = 60.0
    origin_lon = 126.0
    origin_lat = 38.0
    origin_x = 43.0
    origin_y = 136.0
    rad = math.pi / 180.0
    re = earth_radius_km / grid_km
    slat1 = standard_lat_1 * rad
    slat2 = standard_lat_2 * rad
    olon = origin_lon * rad
    olat = origin_lat * rad
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(
        math.tan(math.pi * 0.25 + slat2 * 0.5)
        / math.tan(math.pi * 0.25 + slat1 * 0.5)
    )
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5) ** sn * math.cos(slat1) / sn
    ro = re * sf / math.tan(math.pi * 0.25 + olat * 0.5) ** sn
    ra = re * sf / math.tan(math.pi * 0.25 + latitude * rad * 0.5) ** sn
    theta = longitude * rad - olon
    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= sn
    nx = math.floor(ra * math.sin(theta) + origin_x + 0.5)
    ny = math.floor(ro - ra * math.cos(theta) + origin_y + 0.5)
    return int(nx), int(ny)


def select_morning_base(
    now: datetime,
    base_time: str = "0500",
    availability_delay_minutes: int = 15,
) -> datetime:
    """Select today's 05 KST release, or yesterday's before it is available."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    now = now.astimezone(KST)
    hour, minute = int(base_time[:2]), int(base_time[2:])
    candidate = datetime.combine(now.date(), time(hour, minute), tzinfo=KST)
    if now < candidate + timedelta(minutes=availability_delay_minutes):
        candidate -= timedelta(days=1)
    return candidate


def parse_pcp(value) -> dict:
    """Parse KMA PCP numeric and categorical strings without hiding uncertainty."""
    raw = "" if value is None else str(value).strip()
    compact = raw.replace(" ", "").replace("㎜", "mm")
    if not compact or "강수없음" in compact or compact in {"없음", "-"}:
        return {
            "raw": raw,
            "estimate_mm": 0.0,
            "lower_bound_mm": 0.0,
            "upper_bound_mm": 0.0,
            "categorical": bool(raw and not re.fullmatch(r"0+(?:\.0+)?", compact)),
            "parse_status": "ok",
        }
    numbers = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", compact)]
    if "미만" in compact and numbers:
        upper = numbers[0]
        return {
            "raw": raw,
            "estimate_mm": upper / 2.0,
            "lower_bound_mm": 0.0,
            "upper_bound_mm": upper,
            "categorical": True,
            "parse_status": "ok",
        }
    if ("~" in compact or "∼" in compact or "-" in compact) and len(numbers) >= 2:
        lower, upper = numbers[0], numbers[1]
        return {
            "raw": raw,
            "estimate_mm": (lower + upper) / 2.0,
            "lower_bound_mm": lower,
            "upper_bound_mm": upper,
            "categorical": True,
            "parse_status": "ok",
        }
    if "이상" in compact and numbers:
        lower = numbers[0]
        return {
            "raw": raw,
            "estimate_mm": lower,
            "lower_bound_mm": lower,
            "upper_bound_mm": None,
            "categorical": True,
            "parse_status": "ok",
        }
    if numbers:
        amount = numbers[0]
        return {
            "raw": raw,
            "estimate_mm": amount,
            "lower_bound_mm": amount,
            "upper_bound_mm": amount,
            "categorical": False,
            "parse_status": "ok",
        }
    return {
        "raw": raw,
        "estimate_mm": None,
        "lower_bound_mm": None,
        "upper_bound_mm": None,
        "categorical": True,
        "parse_status": "unparseable",
    }


def _response_items(document: dict) -> list[dict]:
    try:
        header = document["response"]["header"]
        code = str(header.get("resultCode", ""))
        if code not in {"00", "0000"}:
            raise RuntimeError(f"KMA API returned result code {code or 'unknown'}")
        items = document["response"]["body"]["items"]["item"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError("KMA API response structure is invalid") from exc
    if isinstance(items, dict):
        return [items]
    if not isinstance(items, list):
        raise RuntimeError("KMA API response items are not a list")
    return items


def normalize_next_day_forecast(
    document: dict,
    base_datetime: datetime,
    nx: int,
    ny: int,
    generated_at: datetime,
    source_mode: str = "live",
    required_hour_count: int = 24,
) -> dict:
    if base_datetime.tzinfo is None:
        base_datetime = base_datetime.replace(tzinfo=KST)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=KST)
    target = base_datetime.astimezone(KST).date() + timedelta(days=1)
    target_compact = target.strftime("%Y%m%d")
    hourly_by_time = {}
    for item in _response_items(document):
        if item.get("category") != "PCP" or str(item.get("fcstDate")) != target_compact:
            continue
        fcst_time = str(item.get("fcstTime", "")).zfill(4)
        if not re.fullmatch(r"\d{4}", fcst_time):
            continue
        parsed = parse_pcp(item.get("fcstValue"))
        hourly_by_time[fcst_time] = {
            "forecast_at": datetime.combine(
                target,
                time(int(fcst_time[:2]), int(fcst_time[2:])),
                tzinfo=KST,
            ).isoformat(),
            **parsed,
        }
    expected_times = [f"{hour:02d}00" for hour in range(24)]
    missing_times = [item for item in expected_times if item not in hourly_by_time]
    hourly = [hourly_by_time[item] for item in expected_times if item in hourly_by_time]
    unparseable = [item["forecast_at"] for item in hourly if item["parse_status"] != "ok"]
    estimates = [item["estimate_mm"] for item in hourly if item["estimate_mm"] is not None]
    lowers = [item["lower_bound_mm"] for item in hourly if item["lower_bound_mm"] is not None]
    upper_unbounded = any(item["upper_bound_mm"] is None for item in hourly)
    uppers = [item["upper_bound_mm"] for item in hourly if item["upper_bound_mm"] is not None]
    complete = len(hourly) == required_hour_count and not missing_times and not unparseable
    first_rain = next((item["forecast_at"] for item in hourly if (item["estimate_mm"] or 0) > 0), None)
    return {
        "schema_version": "1.0",
        "dataset_id": "KMA-VILAGE-FORECAST-V18",
        "status": "complete" if complete else "incomplete",
        "generated_at": generated_at.astimezone(KST).isoformat(),
        "source": {
            "provider": "기상청",
            "service": "단기예보 조회서비스 getVilageFcst",
            "mode": source_mode,
            "category": "PCP",
            "spatial_resolution": "5km grid",
        },
        "base_datetime": base_datetime.astimezone(KST).isoformat(),
        "target_date": target.isoformat(),
        "grid": {"nx": nx, "ny": ny},
        "coverage": {
            "required_hour_count": required_hour_count,
            "received_hour_count": len(hourly),
            "missing_times": missing_times,
            "unparseable_times": unparseable,
            "complete_24h": complete,
        },
        "rain_24h": {
            "representative_estimate_mm": round(sum(estimates), 2),
            "lower_bound_mm": round(sum(lowers), 2),
            "upper_bound_mm": None if upper_unbounded else round(sum(uppers), 2),
            "contains_categorical_values": any(item["categorical"] for item in hourly),
            "first_rain_at": first_rain,
            "aggregation": "sum of 24 hourly PCP values; categorical values retain bounds",
        },
        "hourly_pcp": hourly,
    }


class KmaForecastClient:
    def __init__(self, api_url: str, service_key: str):
        self.api_url = api_url
        self.service_key = service_key

    def fetch(self, base_datetime: datetime, nx: int, ny: int) -> dict:
        params = urllib.parse.urlencode(
            {
                "pageNo": 1,
                "numOfRows": 1000,
                "dataType": "JSON",
                "base_date": base_datetime.strftime("%Y%m%d"),
                "base_time": base_datetime.strftime("%H%M"),
                "nx": nx,
                "ny": ny,
            }
        )
        encoded_key = urllib.parse.quote(self.service_key, safe="%")
        url = f"{self.api_url}?serviceKey={encoded_key}&{params}"
        request = urllib.request.Request(url, headers={"User-Agent": "ICTCB-Flood-V18/1.0"})
        last_error = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=25) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                last_error = RuntimeError(f"KMA HTTP status {exc.code}")
            except urllib.error.URLError as exc:
                last_error = RuntimeError(f"KMA network error: {type(exc.reason).__name__}")
            except json.JSONDecodeError:
                last_error = RuntimeError("KMA API returned invalid JSON")
            if attempt < 2:
                time_module.sleep(0.6 * (attempt + 1))
        raise last_error or RuntimeError("KMA API request failed")

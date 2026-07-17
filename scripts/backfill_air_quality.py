#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

CITIES = [
    {"name": "London", "lat": 51.5074, "lon": -0.1278},
    {"name": "Paris", "lat": 48.8566, "lon": 2.3522},
    {"name": "New York", "lat": 40.7128, "lon": -74.0060},
    {"name": "Tokyo", "lat": 35.6762, "lon": 139.6503},
    {"name": "Delhi", "lat": 28.6139, "lon": 77.2090},
]

AQI_LABELS = {1: "Good", 2: "Fair", 3: "Moderate", 4: "Poor", 5: "Very Poor"}

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
FIELDNAMES = [
    "run_timestamp",
    "city",
    "lat",
    "lon",
    "reading_at",
    "aqi",
    "aqi_label",
    "co",
    "no",
    "no2",
    "o3",
    "so2",
    "pm2_5",
    "pm10",
    "nh3",
]

HISTORY_URL = "https://api.openweathermap.org/data/2.5/air_pollution/history"
CHUNK = timedelta(days=30)


def city_slug(name: str) -> str:
    return name.lower().replace(" ", "_")


def subtract_months(dt: datetime, months: int) -> datetime:
    month_index = dt.month - 1 - months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, 28) 
    return dt.replace(year=year, month=month, day=day)


def determine_first_launch() -> datetime:
    earliest = None
    for city in CITIES:
        city_file = RAW_DIR / f"{city_slug(city['name'])}.csv"
        if not city_file.exists():
            continue
        with city_file.open() as f:
            for row in csv.DictReader(f):
                if not row["run_timestamp"]:
                    continue
                ts = datetime.fromisoformat(row["run_timestamp"])
                if earliest is None or ts < earliest:
                    earliest = ts
    if earliest is not None:
        return earliest

    raise SystemExit(
        "Could not determine the DAG's first launch time from data/raw/<city>.csv. "
        "Pass --first-launch 2026-07-15T14:57:21+00:00 explicitly."
    )


def fetch_history(city: dict, start: datetime, end: datetime, api_key: str) -> list[dict]:
    rows = []
    window_start = start
    while window_start < end:
        window_end = min(window_start + CHUNK, end)
        response = requests.get(
            HISTORY_URL,
            params={
                "lat": city["lat"],
                "lon": city["lon"],
                "start": int(window_start.timestamp()),
                "end": int(window_end.timestamp()),
                "appid": api_key,
            },
            timeout=30,
        )
        response.raise_for_status()
        for reading in response.json()["list"]:
            components = reading["components"]
            rows.append(
                {
                    "run_timestamp": "",
                    "city": city["name"],
                    "lat": city["lat"],
                    "lon": city["lon"],
                    "reading_at": datetime.fromtimestamp(
                        reading["dt"], tz=timezone.utc
                    ).isoformat(),
                    "aqi": reading["main"]["aqi"],
                    "aqi_label": AQI_LABELS.get(reading["main"]["aqi"], "Unknown"),
                    **{field: components[field] for field in FIELDNAMES[7:]},
                }
            )
        window_start = window_end
    return rows


def write_city_file(city_name: str, rows: list[dict]) -> None:
    rows = sorted(rows, key=lambda r: r["reading_at"])
    deduped = list({row["reading_at"]: row for row in rows}.values())
    deduped.sort(key=lambda r: r["reading_at"])

    city_file = RAW_DIR / f"{city_slug(city_name)}.csv"
    with city_file.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(deduped)
    print(f"  wrote {len(deduped)} rows -> {city_file.relative_to(REPO_ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", type=int, default=12, help="How many months of history to backfill (default: 12)")
    parser.add_argument("--first-launch", type=str, default=None, help="ISO8601 timestamp to backfill up to (default: auto-detected)")
    parser.add_argument("--api-key", type=str, default=None, help="OpenWeatherMap API key (default: $OPENWEATHER_API_KEY)")
    parser.add_argument("--skip-fetch", action="store_true", help="Skip the live API backfill; just re-dedup the existing per-city files")
    args = parser.parse_args()

    first_launch = (
        datetime.fromisoformat(args.first_launch) if args.first_launch else determine_first_launch()
    )
    start = subtract_months(first_launch, args.months)
    print(f"First DAG launch detected at {first_launch.isoformat()}")
    print(f"Backfilling {args.months} month(s) of history: {start.isoformat()} -> {first_launch.isoformat()}")

    api_key = args.api_key or os.environ.get("OPENWEATHER_API_KEY")
    if not api_key and not args.skip_fetch:
        raise SystemExit(
            "No API key found. Set OPENWEATHER_API_KEY or pass --api-key, "
            "or use --skip-fetch to only re-dedup existing data."
        )

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    for city in CITIES:
        print(f"{city['name']}:")
        rows = []

        city_file = RAW_DIR / f"{city_slug(city['name'])}.csv"
        if city_file.exists():
            with city_file.open() as f:
                rows.extend(csv.DictReader(f))

        if not args.skip_fetch:
            print(f"  fetching history from {start.date()} to {first_launch.date()}...")
            rows.extend(fetch_history(city, start, first_launch, api_key))

        write_city_file(city["name"], rows)


if __name__ == "__main__":
    main()

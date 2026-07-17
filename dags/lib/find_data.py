from datetime import datetime, timezone
from pathlib import Path
import csv
import json
import os
import requests

AQI_LABELS = {
    1: "Good",
    2: "Fair",
    3: "Moderate",
    4: "Poor",
    5: "Very Poor",
}

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

RAW_DIR = Path("data/raw")


CITY_NAMES = ["delhi", "london", "new york", "paris", "tokyo"]


def sanitize_city_name(name: str) -> str:
    return name.lower().replace(" ", "_")


def geocode_city(name: str, api_key: str) -> dict:
    response = requests.get(
        "http://api.openweathermap.org/geo/1.0/direct",
        params={"q": name, "appid": api_key},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    if not data:
        raise ValueError(f"City '{name}' not found")
    return {"name": data[0]["name"], "lat": data[0]["lat"], "lon": data[0]["lon"]}


def fetch_and_write() -> list[str]:
    api_key = os.getenv("OPENWEATHER_API_KEY")
    if not api_key:
        raise ValueError("OPENWEATHER_API_KEY environment variable is not set")

    run_timestamp = datetime.now(timezone.utc).isoformat()
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    city_names = list(CITY_NAMES)
    cities_env = os.getenv("CITIES")
    if cities_env:
        city_names.extend(json.loads(cities_env))

    written_files = []
    errors = []

    for city_name in city_names:
        try:
            geo = geocode_city(city_name, api_key)
            response = requests.get(
                "https://api.openweathermap.org/data/2.5/air_pollution",
                params={"lat": geo["lat"], "lon": geo["lon"], "appid": api_key},
                timeout=15,
            )
            response.raise_for_status()
            reading = response.json()["list"][0]
            components = reading["components"]
            row = {
                "run_timestamp": run_timestamp,
                "city": geo["name"],
                "lat": geo["lat"],
                "lon": geo["lon"],
                "reading_at": datetime.fromtimestamp(
                    reading["dt"], tz=timezone.utc
                ).isoformat(),
                "aqi": reading["main"]["aqi"],
                "aqi_label": AQI_LABELS.get(reading["main"]["aqi"], "Unknown"),
                **{field: components[field] for field in FIELDNAMES[7:]},
            }

            city_filename = sanitize_city_name(geo["name"]) + ".csv"
            city_file = RAW_DIR / city_filename
            file_exists = city_file.exists()
            with city_file.open("a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(row)
            written_files.append(str(city_file))
        except Exception as e:
            errors.append(f"Failed to fetch data for {city_name}: {e}")

    if errors:
        print("\n".join(errors))

    if not written_files:
        raise RuntimeError("No data was successfully fetched for any city")

    return written_files

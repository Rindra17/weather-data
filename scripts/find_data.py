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
OUTPUT_FILE = RAW_DIR / f"{datetime.now(timezone.utc).isoformat()}_weather_data.csv"

CITIES = json.loads(os.getenv["CITIES"])


def fetch_and_write() -> str:
    api_key = os.getenv("OPENWEATHER_API_KEY")
    run_timestamp = datetime.now(timezone.utc).isoformat()

    rows = []
    for city in CITIES:
        response = requests.get(
            "https://api.openweathermap.org/data/2.5/air_pollution",
            params={"lat": city["lat"], "lon": city["lon"], "appid": api_key},
            timeout=15,
        )
        response.raise_for_status()
        reading = response.json()["list"][0]
        components = reading["components"]
        rows.append(
            {
                "run_timestamp": run_timestamp,
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

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    file_exists = OUTPUT_FILE.exists()
    with OUTPUT_FILE.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)

    return str(OUTPUT_FILE)
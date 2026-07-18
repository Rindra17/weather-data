import csv
from datetime import datetime, timezone
from pathlib import Path

import requests
from airflow.sdk import Variable

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

BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "data" / "raw"

CITIES = [
    {"name": "London", "lat": 51.5074, "lon": -0.1278},
    {"name": "Paris", "lat": 48.8566, "lon": 2.3522},
    {"name": "New York", "lat": 40.7128, "lon": -74.0060},
    {"name": "Tokyo", "lat": 35.6762, "lon": 139.6503},
    {"name": "Delhi", "lat": 28.6139, "lon": 77.2090},
]


def sanitize_city_name(name: str) -> str:
    return name.lower().replace(" ", "_")


def fetch_and_write() -> list[str]:
    api_key = Variable.get("OPENWEATHER_API_KEY")
    if not api_key:
        raise ValueError("OPENWEATHER_API_KEY environment variable is not set")

    run_timestamp = datetime.now(timezone.utc).isoformat()
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    cities = list(CITIES)

    written_files = []
    errors = []

    for city in cities:
        try:
            response = requests.get(
                "https://api.openweathermap.org/data/2.5/air_pollution",
                params={"lat": city["lat"], "lon": city["lon"], "appid": api_key},
                timeout=15,
            )
            response.raise_for_status()
            reading = response.json()["list"][0]
            components = reading["components"]
            row = {
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

            city_filename = sanitize_city_name(city["name"]) + ".csv"
            city_file = RAW_DIR / city_filename
            file_exists = city_file.exists()
            with city_file.open("a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(row)
            written_files.append(str(city_file))
        except Exception as e:
            errors.append(f"Failed to fetch data for {city}: {e}")

    if errors:
        print("\n".join(errors))

    if not written_files:
        raise RuntimeError("No data was successfully fetched for any city")

    return written_files

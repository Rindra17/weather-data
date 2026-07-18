from pathlib import Path
import csv

BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"

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
    "dominant_pollutant",
]

NUMERIC_FIELDS = ["lat", "lon", "co", "no", "no2", "o3", "so2", "pm2_5", "pm10", "nh3"]

POLLUTANT_THRESHOLDS = {
    "pm2_5": 25,
    "pm10": 50,
    "no2": 200,
    "o3": 180,
    "so2": 350,
}


def load_raw_rows(input_file: Path) -> list[dict]:
    with input_file.open(newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def clean_row(row: dict) -> dict | None:
    try:
        for field in NUMERIC_FIELDS:
            value = row.get(field, "").strip()
            if value == "":
                return None
            row[field] = float(value)

        row["aqi"] = int(row["aqi"])

        if not (1 <= row["aqi"] <= 5):
            return None
        if not (-90 <= row["lat"] <= 90) or not (-180 <= row["lon"] <= 180):
            return None

    except (ValueError, KeyError):
        return None

    return row


def enrich_row(row: dict) -> dict:
    dominant = None
    max_ratio = 0.0
    for pollutant, threshold in POLLUTANT_THRESHOLDS.items():
        ratio = row.get(pollutant, 0) / threshold
        if ratio > max_ratio:
            max_ratio = ratio
            dominant = pollutant
    row["dominant_pollutant"] = dominant or "unknown"
    return row


def deduplicate(rows: list[dict]) -> list[dict]:
    seen = set()
    unique_rows = []
    for row in rows:
        key = (row["city"], row["reading_at"])
        if key not in seen:
            seen.add(key)
            unique_rows.append(row)
    return unique_rows


def transform() -> str:
    """Combine every CSV in RAW_DIR into a single deduplicated clean file,
    overwriting it on each call."""
    cleaned_rows = []
    for raw_file in sorted(RAW_DIR.glob("*.csv")):
        for row in load_raw_rows(raw_file):
            cleaned = clean_row(row)
            if cleaned is not None:
                cleaned_rows.append(enrich_row(cleaned))

    cleaned_rows = deduplicate(cleaned_rows)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    output_file = PROCESSED_DIR / "weather_data_clean.csv"

    with output_file.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(cleaned_rows)

    return str(output_file)

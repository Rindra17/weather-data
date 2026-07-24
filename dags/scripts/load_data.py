import csv
import os
import sys
from datetime import datetime
from pathlib import Path
from dotenv import dotenv_values
import psycopg2
from psycopg2.extras import execute_values

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent
CLEAN_FILE = PROJECT_ROOT / "data" / "clean" / "weather_data_clean.csv"
SCHEMA_FILE = BASE_DIR / "sql" / "schema.sql"

ENV_FILE = PROJECT_ROOT / ".env"
if ENV_FILE.exists():
    DB_URL = dotenv_values(ENV_FILE).get("DATABASE_URL")
else:
    DB_URL = os.environ.get("DATABASE_URL")


def create_schema(conn):
    with SCHEMA_FILE.open("r", encoding="utf-8") as f:
        sql_script = f.read()

    with conn.cursor() as cur:
        try:
            cur.execute(sql_script)
            conn.commit()
            print("Schema created successfully!")
        except psycopg2.Error as e:
            conn.rollback()
            print(f"Error while executing schema.sql:")
            print(f" {e}")
            raise


def load_data(conn):
    print(f"Reading file: {CLEAN_FILE}")

    rows = []
    with CLEAN_FILE.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    if not rows:
        print("No data to load")
        return

    try:
        with conn.cursor() as cur:
            print("Loading cities...")
            city_tuples = {
                row["city"]: (
                    row["city"],
                    row["country"],
                    float(row["lat"]),
                    float(row["lon"]),
                )
                for row in rows
            }.values()

            city_result = execute_values(
                cur,
                """
                INSERT INTO dim_city (city_name,country, latitude, longitude)
                VALUES %s
                ON CONFLICT (city_name) DO UPDATE SET city_name = EXCLUDED.city_name
                RETURNING city_id, city_name
                """,
                list(city_tuples),
                fetch=True,
            )
            cities = {name: city_id for city_id, name in city_result}
            print(f" {len(cities)} cities loaded")

            print("Loading periods...")
            time_rows = {}
            for row in rows:
                reading_at = datetime.fromisoformat(
                    row["reading_at"].replace("Z", "+00:00")
                )
                if reading_at not in time_rows:
                    day_of_week = reading_at.strftime("%A")
                    is_weekend = reading_at.weekday() >= 5
                    quarter = (reading_at.month - 1) // 3 + 1
                    time_rows[reading_at] = (
                        reading_at,
                        reading_at.date(),
                        reading_at.hour,
                        day_of_week,
                        is_weekend,
                        reading_at.month,
                        reading_at.year,
                        quarter,
                    )

            time_result = execute_values(
                cur,
                """
                INSERT INTO dim_time (
                    reading_at, date, hour, day_of_week,
                    is_weekend, month, year, quarter
                ) VALUES %s
                ON CONFLICT (reading_at) DO UPDATE SET reading_at = EXCLUDED.reading_at
                RETURNING time_id, reading_at
                """,
                list(time_rows.values()),
                fetch=True,
            )
            times = {reading_at: time_id for time_id, reading_at in time_result}
            print(f" {len(times)} periods loaded")

            print("Loading facts...")
            fact_tuples = []
            for row in rows:
                reading_at = datetime.fromisoformat(
                    row["reading_at"].replace("Z", "+00:00")
                )
                fact_tuples.append(
                    (
                        times[reading_at],
                        cities[row["city"]],
                        int(row["aqi"]),
                        row["aqi_label"],
                        float(row["co"]),
                        float(row["no"]),
                        float(row["no2"]),
                        float(row["o3"]),
                        float(row["so2"]),
                        float(row["pm2_5"]),
                        float(row["pm10"]),
                        float(row["nh3"]),
                        row.get("dominant_pollutant", "unknown"),
                    )
                )

            fact_result = execute_values(
                cur,
                """
                INSERT INTO fact_air_quality (
                    time_id, city_id, aqi, aqi_label,
                    co, no, no2, o3, so2, pm2_5, pm10, nh3,
                    dominant_pollutant
                ) VALUES %s
                ON CONFLICT (time_id, city_id) DO NOTHING
                RETURNING fact_id
                """,
                fact_tuples,
                page_size=1000,
                fetch=True,
            )
            inserted = len(fact_result)
            skipped = len(fact_tuples) - inserted

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    print(f" {inserted} facts inserted")
    print(f" {skipped} facts skipped (already exist)")


def show_stats(conn):
    print("\nData warehouse statistics:")

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM dim_city")
        cities = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM dim_time")
        times = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM fact_air_quality")
        facts = cur.fetchone()[0]

        cur.execute("""
            SELECT MIN(reading_at), MAX(reading_at)
            FROM dim_time
        """)
        min_date, max_date = cur.fetchone()

        print(f" Cities: {cities}")
        print(f" Periods: {times}")
        print(f" Facts: {facts}")
        if min_date and max_date:
            print(f" Period: {min_date.date()} -> {max_date.date()}")


def main():
    print("Starting data warehouse loading...")
    print("=" * 50)

    if not DB_URL:
        print(
            "Undefined DATABASE_URL in .env file. Please set it before running the script."
        )
        sys.exit(1)

    if not CLEAN_FILE.exists():
        print(f"CLEAN file not found: {CLEAN_FILE}")
        print("Run the pipeline first to generate the clean file")
        sys.exit(1)

    if not SCHEMA_FILE.exists():
        print(f"schema.sql file not found: {SCHEMA_FILE}")
        print("   Please be sure that sql/schema.sql exists")
        sys.exit(1)

    conn = None
    try:
        conn = psycopg2.connect(DB_URL)
        print("Connection successful")

        create_schema(conn)
        load_data(conn)
        show_stats(conn)

        print("\nLoading completed successfully!")

    except psycopg2.OperationalError as e:
        print(f"\nConnection error to Neon: {e}")
        print(
            "Please check your DATABASE_URL in the .env file and ensure that your Neon database is running."
        )
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()

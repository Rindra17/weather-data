import csv
import os
import sys
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import execute_values

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
CLEAN_FILE = BASE_DIR / "data" / "clean" / "weather_data_clean.csv"
SCHEMA_FILE = BASE_DIR / "sql" / "schema.sql"
DB_URL = os.getenv("DATABASE_URL")

if not DB_URL:
    print("Undefined DATABASE_URL in .env file. Please set it before running the script.")
    sys.exit(1)

if not CLEAN_FILE.exists():
    print(f"CLEAN file not found: {CLEAN_FILE}")
    print("Run the pipeline first to generate the clean file")
    sys.exit(1)

if not SCHEMA_FILE.exists():
    print(f"schema.sql file not found: {SCHEMA_FILE}")
    print("   Please be sure that sql/schema.sql exists")
    sys.exit(1)

def create_schema(conn):
    
    with SCHEMA_FILE.open('r', encoding='utf-8') as f:
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
    with CLEAN_FILE.open('r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
        
    if not rows:
        print("No data to load")
        return
    
    print("Loading cities...")
    cities = {}
    with conn.cursor() as cur:
        for row in rows:
            city_name = row['city']
            if city_name not in cities:
                cur.execute(
                    "SELECT city_key FROM dim_city WHERE city_name = %s",
                    (city_name,)
                )
                result = cur.fetchone()
                if result:
                    cities[city_name] = result[0]
                else:
                    cur.execute("""
                        INSERT INTO dim_city (city_name, latitude, longitude)
                        VALUES (%s, %s, %s)
                        RETURNING city_key
                    """, (city_name, float(row['lat']), float(row['lon'])))
                    cities[city_name] = cur.fetchone()[0]
        conn.commit()
    
    print(f"   ✅ {len(cities)} cities loaded")
    
    print("Loading periods...")
    times = {}
    with conn.cursor() as cur:
        for row in rows:
            reading_at = datetime.fromisoformat(row['reading_at'].replace('Z', '+00:00'))
            time_key = f"{reading_at.isoformat()}"
            
            if time_key not in times:
                cur.execute(
                    "SELECT time_key FROM dim_time WHERE reading_at = %s",
                    (reading_at,)
                )
                result = cur.fetchone()
                if result:
                    times[time_key] = result[0]
                else:
                    day_of_week = reading_at.strftime('%A')
                    is_weekend = reading_at.weekday() >= 5
                    quarter = (reading_at.month - 1) // 3 + 1
                    
                    cur.execute("""
                        INSERT INTO dim_time (
                            reading_at, date, hour, day_of_week, 
                            is_weekend, month, year, quarter
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING time_key
                    """, (
                        reading_at,
                        reading_at.date(),
                        reading_at.hour,
                        day_of_week,
                        is_weekend,
                        reading_at.month,
                        reading_at.year,
                        quarter
                    ))
                    times[time_key] = cur.fetchone()[0]
        conn.commit()
    
    print(f"   ✅ {len(times)} periods loaded")
    
    print("Loading facts...")
    inserted = 0
    skipped = 0
    
    with conn.cursor() as cur:
        for row in rows:
            reading_at = datetime.fromisoformat(row['reading_at'].replace('Z', '+00:00'))
            time_key = times[f"{reading_at.isoformat()}"]
            city_key = cities[row['city']]
            
            cur.execute("""
                SELECT fact_key FROM fact_air_quality
                WHERE time_key = %s AND city_key = %s
            """, (time_key, city_key))
            
            if cur.fetchone():
                skipped += 1
                continue
            
            try:
                cur.execute("""
                    INSERT INTO fact_air_quality (
                        time_key, city_key, aqi, aqi_label,
                        co, no, no2, o3, so2, pm2_5, pm10, nh3,
                        dominant_pollutant
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    time_key,
                    city_key,
                    int(row['aqi']),
                    row['aqi_label'],
                    float(row['co']),
                    float(row['no']),
                    float(row['no2']),
                    float(row['o3']),
                    float(row['so2']),
                    float(row['pm2_5']),
                    float(row['pm10']),
                    float(row['nh3']),
                    row.get('dominant_pollutant', 'unknown')
                ))
                inserted += 1
            except Exception as e:
                print(f" Error on line {row}: {e}")
        
        conn.commit()
    
    print(f" {inserted} facts inserted")
    print(f" {skipped} ignored files (already exist)")


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
    
    try:
        conn = psycopg2.connect(DB_URL)
        print("Connection successful")
        
        create_schema(conn)
        
        load_data(conn)
        
        show_stats(conn)
        
        conn.close()
        
        print("\nLoading completed successfully!")
        
    except psycopg2.OperationalError as e:
        print(f"\nConnection error to Neon: {e}")
        print("Please check your DATABASE_URL in the .env file and ensure that your Neon database is running.")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
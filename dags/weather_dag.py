from airflow.decorators import dag, task
from datetime import datetime
from pathlib import Path
import sys

DAGS_DIR = Path(__file__).resolve().parent

for p in [
    str(DAGS_DIR),
    str(DAGS_DIR.parent / "scripts"),
    "/opt/airflow/scripts",
]:
    if p not in sys.path:
        sys.path.insert(0, p)

import find_data
import transform_data

RAW_DIR = Path("/opt/airflow/raw")
CLEAN_DIR = Path("/opt/airflow/clean")


@dag(
    schedule="0 * * * *",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
)
def weather_pipeline():

    @task
    def extract():
        find_data.RAW_DIR = RAW_DIR
        return find_data.fetch_and_write()

    @task
    def transform(raw_files: list[str]):
        transform_data.PROCESSED_DIR = CLEAN_DIR
        for f in raw_files:
            transform_data.transform(f)

    transform(extract())


weather_pipeline()

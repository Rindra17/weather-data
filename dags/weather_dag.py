from airflow.decorators import dag, task
from datetime import datetime
from pathlib import Path

from lib import find_data, transform_data

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

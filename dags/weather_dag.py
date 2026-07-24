from airflow.sdk import dag, task
from datetime import datetime
from pathlib import Path

from scripts import extract_data, transform_data

RAW_DIR = Path("/opt/airflow/raw")
CLEAN_DIR = Path("/opt/airflow/clean")


@dag(
    schedule="0 * * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
)
def weather_pipeline():

    @task
    def extract():
        extract_data.RAW_DIR = RAW_DIR
        return extract_data.fetch_and_write()

    @task
    def transform(raw_files: list[str]):
        transform_data.RAW_DIR = RAW_DIR
        transform_data.CLEAN_DIR = CLEAN_DIR
        return transform_data.transform()

    transform(extract())


weather_pipeline()

from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator

from src.etl import extract, load, transform

with DAG(
    "intersections_etl",
    default_args={"owner": "admin"},
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
) as dag:
    extract_task = PythonOperator(task_id="extract", python_callable=extract)
    transform_task = PythonOperator(task_id="transform", python_callable=transform)
    load_task = PythonOperator(task_id="load", python_callable=load)

    extract_task >> transform_task >> load_task

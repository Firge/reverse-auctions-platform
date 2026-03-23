#!/usr/bin/env python3
import os
import sys
import subprocess
import psycopg
from pathlib import Path

def is_database_empty(db_url: str) -> bool:
    try:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'catalog_items'
                    );
                """)
                table_exists = cur.fetchone()[0]
                if not table_exists:
                    return True

                cur.execute("SELECT COUNT(*) FROM catalog_items;")
                count = cur.fetchone()[0]
                return count == 0
    except Exception as e:
        print(f"Ошибка подключения к БД: {e}", file=sys.stderr)
        sys.exit(1)

def run_pipeline():
    print("База данных пуста. Запускаем парсинг и загрузку...")

    pdf_source = Path("./tools/source/ТССЦ-1_Часть_1._Материалы_для_общестроительных_работ.pdf")
    if not pdf_source.exists():
        print(f"Файл PDF не найден: {pdf_source}", file=sys.stderr)
        sys.exit(1)

    parse_cmd = [
        "python", "tools/parse_tssc.py",
        "--method", "camelot",
        "--page-start", "3",
        "--page-end", "357",
        "--progress-every", "25"
    ]
    print("Выполняется парсинг...")
    subprocess.run(parse_cmd, check=True)

    load_cmd = [
        "python", "tools/load_tssc_to_postgres.py",
        "--input-glob", "/app/out/items_*.jsonl",
        "--schema", "/app/tools/schema.sql"
    ]
    print("Выполняется загрузка...")
    subprocess.run(load_cmd, check=True)

    print("Инициализация завершена успешно.")

def main():
    db_url = os.environ.get("DATABASE_URL", "postgresql://catalog:catalog@postgres:5432/catalog")

    if is_database_empty(db_url):
        run_pipeline()
    else:
        print("База данных уже содержит данные, инициализация не требуется.")

if __name__ == "__main__":
    main()

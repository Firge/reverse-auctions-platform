from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import psycopg
from psycopg import errors as pg_errors


@dataclass
class Item:
    code: str
    name: str
    unit: str
    price_release: Optional[str]
    price_estimate: Optional[str]
    section: Optional[str]
    subsection: Optional[str]
    group: Optional[str]
    spec: Optional[str]
    source_file: str


def parse_number(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    if value == "":
        return None
    return value.replace(" ", "").replace(",", ".")


def iter_jsonl(path: Path) -> Iterable[Item]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            yield Item(
                code=data.get("code", ""),
                name=data.get("name", ""),
                unit=data.get("unit", ""),
                price_release=data.get("price_release"),
                price_estimate=data.get("price_estimate"),
                section=data.get("section"),
                subsection=data.get("subsection"),
                group=data.get("group"),
                spec=data.get("spec"),
                source_file=path.name,
            )


def iter_csv(path: Path) -> Iterable[Item]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield Item(
                code=row.get("code", ""),
                name=row.get("name", ""),
                unit=row.get("unit", ""),
                price_release=row.get("price_release"),
                price_estimate=row.get("price_estimate"),
                section=row.get("section"),
                subsection=row.get("subsection"),
                group=row.get("group"),
                spec=row.get("spec"),
                source_file=path.name,
            )


def get_items(path: Path) -> Iterable[Item]:
    if path.suffix.lower() == ".jsonl":
        return iter_jsonl(path)
    if path.suffix.lower() == ".csv":
        return iter_csv(path)
    raise ValueError(f"unsupported file: {path}")


def ensure_schema(conn: psycopg.Connection, schema_path: Path) -> None:
    sql = schema_path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def get_node_id(
    cur: psycopg.Cursor,
    kind: str,
    name: Optional[str],
    parent_id: Optional[int],
) -> Optional[int]:
    if not name:
        return parent_id

    cur.execute(
        """
        SELECT id
        FROM catalog_nodes
        WHERE kind = %s
          AND name = %s
                    AND ((parent_id IS NULL AND %s::bigint IS NULL) OR parent_id = %s::bigint)
        """,
        (kind, name, parent_id, parent_id),
    )
    row = cur.fetchone()
    if row:
        return row[0]

    try:
        cur.execute(
            """
            INSERT INTO catalog_nodes (kind, name, parent_id)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (kind, name, parent_id),
        )
        return cur.fetchone()[0]
    except pg_errors.UniqueViolation:
        cur.execute(
            """
            SELECT id
            FROM catalog_nodes
            WHERE kind = %s
              AND name = %s
                            AND ((parent_id IS NULL AND %s::bigint IS NULL) OR parent_id = %s::bigint)
            """,
            (kind, name, parent_id, parent_id),
        )
        row = cur.fetchone()
        return row[0] if row else None


def get_source_id(cur: psycopg.Cursor, name: str) -> int:
    cur.execute(
        """
        INSERT INTO catalog_sources (name)
        VALUES (%s)
        ON CONFLICT (name)
        DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """,
        (name,),
    )
    return cur.fetchone()[0]


def load_items(conn: psycopg.Connection, items: Iterable[Item]) -> int:
    inserted = 0
    with conn.cursor() as cur:
        for item in items:
            section_id = get_node_id(cur, "section", item.section, None)
            subsection_id = get_node_id(cur, "subsection", item.subsection, section_id)
            group_id = get_node_id(cur, "group", item.group, subsection_id)
            spec_id = get_node_id(cur, "spec", item.spec, group_id)

            source_id = get_source_id(cur, item.source_file)

            cur.execute(
                """
                INSERT INTO catalog_items (
                    code, name, unit, price_release, price_estimate, node_id, source_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    item.code,
                    item.name,
                    item.unit,
                    parse_number(item.price_release),
                    parse_number(item.price_estimate),
                    spec_id,
                    source_id,
                ),
            )
            inserted += 1

    conn.commit()
    return inserted


def main() -> None:
    parser = argparse.ArgumentParser(description="Load parsed TSSC items into Postgres.")
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        help="Input file (csv/jsonl). Can be used multiple times.",
    )
    parser.add_argument(
        "--input-glob",
        default="/app/out/items_*.jsonl",
        help="Glob for inputs if --input not provided",
    )
    parser.add_argument(
        "--schema",
        default="/app/tools/schema.sql",
        help="Path to schema SQL",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Database URL (overrides DATABASE_URL env)",
    )
    args = parser.parse_args()

    db_url = args.db or os.getenv("DATABASE_URL") or "postgresql://catalog:catalog@postgres:5432/catalog"

    if args.input:
        inputs = [Path(p) for p in args.input]
    else:
        glob_path = Path(args.input_glob)
        if glob_path.is_absolute():
            inputs = list(glob_path.parent.glob(glob_path.name))
        else:
            inputs = list(Path().glob(args.input_glob))

    if not inputs:
        raise SystemExit("No input files found")

    schema_path = Path(args.schema)

    with psycopg.connect(db_url) as conn:
        ensure_schema(conn, schema_path)
        total = 0
        for path in inputs:
            items = get_items(path)
            count = load_items(conn, items)
            total += count
            print(f"loaded {count} items from {path.name}")

    print(f"total loaded: {total}")


if __name__ == "__main__":
    main()

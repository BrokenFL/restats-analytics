"""Reconcile closed MLS export rows against the local SQLite database.

This is a publication gate for the closed-history refresh. It checks the source
export by listing identity and transaction keys rather than trusting local
coverage watermarks or aggregate counts.
"""

import argparse
import csv
import json
import re
import sqlite3
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path


DEFAULT_CITIES = [
    "Palm Beach",
    "Wellington",
    "Boca Raton",
    "Delray Beach",
    "South Palm Beach",
]


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_") or "city"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _date_text(value: str | None) -> str:
    parsed = _parse_date(value)
    return parsed.isoformat() if parsed else ""


def _number(value: str | None) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def _text_norm(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _listing_aliases(listing_number: str) -> list[str]:
    """Return source/legacy aliases used by the MLS canonicalization layer."""
    value = str(listing_number or "").strip().upper()
    aliases = [value]
    plain = re.fullmatch(r"([AFR])(\d+)", value)
    prefixed = re.fullmatch(r"([AFR])X-(\d+)", value)
    if plain:
        aliases.append(f"{plain.group(1)}X-{plain.group(2)}")
    elif prefixed:
        aliases.append(f"{prefixed.group(1)}{prefixed.group(2)}")
    return list(dict.fromkeys(aliases))


def _latest_csv(directory: Path) -> Path | None:
    files = [path for path in directory.glob("*.csv") if path.is_file()]
    return max(files, key=lambda path: path.stat().st_mtime) if files else None


def _source_rows(path: Path, city: str, start_date: date, end_date: date | None) -> tuple[list[dict], list[str]]:
    rows = []
    duplicate_ids = []
    seen = set()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            listing_number = str(raw.get("Listing Number") or "").strip().upper()
            close_date = _parse_date(raw.get("Close Date"))
            if not listing_number or close_date is None:
                continue
            if close_date < start_date or (end_date is not None and close_date > end_date):
                continue
            if listing_number in seen:
                duplicate_ids.append(listing_number)
            seen.add(listing_number)
            rows.append(
                {
                    "listing_number": listing_number,
                    "city": str(raw.get("City") or city).strip(),
                    "status": str(raw.get("Status") or "").strip().upper(),
                    "close_date": close_date.isoformat(),
                    "close_price": _number(raw.get("Close Price")),
                    "parcel_id": str(raw.get("Parcel Number") or "").strip(),
                    "short_address": str(raw.get("Short Address") or "").strip(),
                    "source_file": str(path),
                }
            )
    return rows, sorted(set(duplicate_ids))


def _local_rows(conn: sqlite3.Connection, listing_numbers: list[str]) -> dict[str, dict]:
    if not listing_numbers:
        return {}
    placeholders = ",".join("?" for _ in listing_numbers)
    query = f"""
        SELECT listing_number, city, status, sold_date, sold_price, parcel_id, geo_zone, short_address
        FROM listing_details
        WHERE listing_number IN ({placeholders})
    """
    return {
        row[0]: {
            "listing_number": row[0],
            "city": row[1] or "",
            "status": row[2] or "",
            "sold_date": _date_text(row[3]),
            "sold_price": row[4],
            "parcel_id": row[5] or "",
            "geo_zone": row[6] or "",
            "short_address": row[7] or "",
        }
        for row in conn.execute(query, listing_numbers).fetchall()
    }


def _local_closed_rows(
    conn: sqlite3.Connection,
    city: str,
    start_date: date,
    end_date: date | None,
) -> list[dict]:
    params: list[str] = [city, start_date.isoformat()]
    end_clause = ""
    if end_date is not None:
        end_clause = "AND DATE(sold_date) <= ?"
        params.append(end_date.isoformat())
    query = f"""
        SELECT listing_number, city, status, sold_date, sold_price, parcel_id, geo_zone, short_address
        FROM listing_details
        WHERE LOWER(TRIM(COALESCE(city, ''))) = LOWER(TRIM(?))
          AND UPPER(TRIM(COALESCE(status, ''))) = 'C'
          AND UPPER(TRIM(COALESCE(listing_number, ''))) NOT LIKE 'PBC-%'
          AND DATE(sold_date) >= ?
          {end_clause}
    """
    return [
        {
            "listing_number": row[0] or "",
            "city": row[1] or "",
            "status": row[2] or "",
            "sold_date": _date_text(row[3]),
            "sold_price": row[4],
            "parcel_id": row[5] or "",
            "geo_zone": row[6] or "",
            "short_address": row[7] or "",
        }
        for row in conn.execute(query, params).fetchall()
    ]


def _transaction_indexes(local_rows: list[dict]) -> tuple[dict, dict]:
    by_parcel_date = defaultdict(list)
    by_address_date = defaultdict(list)
    for row in local_rows:
        date_key = row.get("sold_date") or ""
        parcel_key = _text_norm(row.get("parcel_id"))
        address_key = _text_norm(row.get("short_address"))
        if date_key and parcel_key:
            by_parcel_date[(parcel_key, date_key)].append(row)
        if date_key and address_key:
            by_address_date[(address_key, date_key)].append(row)
    return by_parcel_date, by_address_date


def _find_transaction_match(source_row: dict, by_parcel_date: dict, by_address_date: dict) -> dict | None:
    close_date = source_row.get("close_date") or ""
    parcel_key = _text_norm(source_row.get("parcel_id"))
    address_key = _text_norm(source_row.get("short_address"))
    candidates = []
    if parcel_key:
        candidates.extend(by_parcel_date.get((parcel_key, close_date), []))
    if not candidates and address_key:
        candidates.extend(by_address_date.get((address_key, close_date), []))
    source_price = source_row.get("close_price")
    for row in candidates:
        local_price = _number(row.get("sold_price"))
        if source_price is not None and local_price is None:
            continue
        if source_price is not None and local_price is not None and abs(source_price - local_price) > 1:
            continue
        if parcel_key and _text_norm(row.get("parcel_id")) == parcel_key:
            return row
        if address_key and _text_norm(row.get("short_address")) == address_key:
            return row
    return None


def reconcile_city(
    conn: sqlite3.Connection,
    city: str,
    export_root: Path,
    export_prefix: str,
    start_date: date,
    end_date: date | None,
) -> dict:
    directory = export_root / f"{export_prefix}_{slugify(city)}"
    export_path = _latest_csv(directory)
    result = {
        "city": city,
        "export_directory": str(directory),
        "export_file": str(export_path) if export_path else None,
        "source_count": 0,
        "empty_source": False,
        "source_duplicate_ids": [],
        "source_city_mismatch": [],
        "missing_in_db": [],
        "wrong_city": [],
        "non_closed_source_status": [],
        "local_not_closed": [],
        "sold_date_mismatch": [],
        "sold_price_mismatch": [],
        "match_type_counts": {"listing_number_or_alias": 0, "transaction_key": 0},
        "resolved_identity_samples": [],
        "passed": False,
    }
    if export_path is None:
        result["error"] = "no export CSV found"
        return result

    source, duplicate_ids = _source_rows(export_path, city, start_date, end_date)
    source_ids = [alias for row in source for alias in _listing_aliases(row["listing_number"])]
    local = _local_rows(conn, sorted(set(source_ids)))
    local_closed = _local_closed_rows(conn, city, start_date, end_date)
    by_parcel_date, by_address_date = _transaction_indexes(local_closed)
    result["source_count"] = len(source)
    result["source_duplicate_ids"] = duplicate_ids
    result["empty_source"] = not source

    for row in source:
        listing_number = row["listing_number"]
        if row["city"].strip().casefold() != city.strip().casefold():
            result["source_city_mismatch"].append(
                {
                    "listing_number": listing_number,
                    "source_city": row["city"],
                    "expected_city": city,
                }
            )
        local_row = None
        match_type = None
        stale_identity_row = None
        wrong_city_row = None
        for alias in _listing_aliases(listing_number):
            candidate = local.get(alias)
            if candidate is None:
                continue
            if candidate["city"].strip().casefold() != city.strip().casefold():
                wrong_city_row = candidate
                continue
            if (
                candidate["status"].strip().upper() == "C"
                and candidate["sold_date"] == row["close_date"]
                and (
                    row["close_price"] is None
                    or (
                        candidate["sold_price"] is not None
                        and abs(row["close_price"] - _number(candidate["sold_price"])) <= 1
                    )
                )
            ):
                local_row = candidate
                match_type = "listing_number_or_alias"
                break
            stale_identity_row = candidate

        if local_row is None:
            transaction_match = _find_transaction_match(row, by_parcel_date, by_address_date)
            if transaction_match is not None:
                local_row = transaction_match
                match_type = "transaction_key"
                if transaction_match["listing_number"] != listing_number:
                    result["resolved_identity_samples"].append(
                        {
                            "source_listing_number": listing_number,
                            "local_listing_number": transaction_match["listing_number"],
                            "match_type": match_type,
                        }
                    )

        if local_row is None and stale_identity_row is not None:
            local_row = stale_identity_row
        if local_row is None and wrong_city_row is not None:
            local_row = wrong_city_row
        if local_row is None:
            result["missing_in_db"].append(listing_number)
            continue
        result["match_type_counts"][match_type or "listing_number_or_alias"] += 1
        if local_row["city"].strip().casefold() != city.strip().casefold():
            result["wrong_city"].append(
                {"listing_number": listing_number, "local_city": local_row["city"], "source_city": city}
            )
        if row["status"] != "C":
            result["non_closed_source_status"].append(
                {"listing_number": listing_number, "source_status": row["status"]}
            )
        if local_row["status"].strip().upper() != "C" or not local_row["sold_date"]:
            result["local_not_closed"].append(
                {
                    "listing_number": listing_number,
                    "local_status": local_row["status"],
                    "local_sold_date": local_row["sold_date"],
                }
            )
        if local_row["sold_date"] != row["close_date"]:
            result["sold_date_mismatch"].append(
                {
                    "listing_number": listing_number,
                    "source_close_date": row["close_date"],
                    "local_sold_date": local_row["sold_date"],
                }
            )
        source_price = row["close_price"]
        local_price = _number(local_row["sold_price"])
        if source_price is not None and (
            local_price is None or abs(source_price - local_price) > 1
        ):
            result["sold_price_mismatch"].append(
                {
                    "listing_number": listing_number,
                    "source_close_price": source_price,
                    "local_sold_price": local_price,
                }
            )

    result["passed"] = not any(
        result[key]
        for key in (
            "empty_source",
            "source_duplicate_ids",
            "source_city_mismatch",
            "missing_in_db",
            "wrong_city",
            "non_closed_source_status",
            "local_not_closed",
            "sold_date_mismatch",
            "sold_price_mismatch",
        )
    )
    return result


def parse_args():
    parser = argparse.ArgumentParser(description="Reconcile closed MLS exports against listing_details.")
    parser.add_argument("--cities", default=",".join(DEFAULT_CITIES))
    parser.add_argument("--export-root", default="output")
    parser.add_argument("--export-prefix", default="mls_closed_exports")
    parser.add_argument("--db-file", default="mls.db")
    parser.add_argument("--from-date", required=True, help="Inclusive close-date start, MM/DD/YYYY or YYYY-MM-DD.")
    parser.add_argument("--to-date", default=None, help="Optional inclusive close-date end.")
    parser.add_argument("--output-json", default="output/audits/mls_closed_reconciliation_latest.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cities = [city.strip() for city in args.cities.split(",") if city.strip()]
    start_date = _parse_date(args.from_date)
    end_date = _parse_date(args.to_date)
    if start_date is None:
        raise SystemExit("--from-date must be a valid date.")
    if args.to_date and end_date is None:
        raise SystemExit("--to-date must be a valid date.")
    if end_date is not None and end_date < start_date:
        raise SystemExit("--to-date must be on or after --from-date.")

    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(args.db_file) as conn:
        cities_result = [
            reconcile_city(
                conn,
                city,
                Path(args.export_root),
                args.export_prefix,
                start_date,
                end_date,
            )
            for city in cities
        ]

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "db_file": args.db_file,
        "export_root": args.export_root,
        "export_prefix": args.export_prefix,
        "from_date": start_date.isoformat(),
        "to_date": end_date.isoformat() if end_date else None,
        "status": "passed" if all(row["passed"] for row in cities_result) else "failed",
        "cities": cities_result,
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"mls_parity_status={payload['status']}")
    print(f"mls_parity_report={output_path}")
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

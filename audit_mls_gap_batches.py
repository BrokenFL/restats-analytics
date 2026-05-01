import argparse
import csv
import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path


DEFAULT_CITIES = [
    "Palm Beach",
    "Wellington",
    "Boca Raton",
    "Delray Beach",
    "South Palm Beach",
]

CRITICAL_FIELDS = [
    "parcel_id",
    "listing_date",
    "status_change_date",
    "short_address",
    "city",
    "sold_date",
    "sold_price",
]

DATE_COLUMNS = [
    "listing_date",
    "status_change_date",
    "under_contract_date",
    "sold_date",
    "withdrawn_date",
    "temp_off_market_date",
    "cancel_date",
    "expiration_date",
]


def parse_args():
    p = argparse.ArgumentParser(description="Audit MLS coverage gaps and propose city/date search batches.")
    p.add_argument("--db-file", default="mls.db")
    p.add_argument("--cities", default=",".join(DEFAULT_CITIES))
    p.add_argument("--batch-days", type=int, default=14, help="Date span per proposed search batch.")
    p.add_argument("--output-json", default="output/audits/mls_gap_batches_latest.json")
    p.add_argument("--output-csv", default="output/audits/mls_gap_batches_latest.csv")
    p.add_argument("--status-mode", default="all", choices=["all", "active-only", "closed-only"])
    return p.parse_args()


def _parse_cities(raw: str):
    return [c.strip() for c in str(raw or "").split(",") if c.strip()]


def _date_or_none(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "")).date()
    except Exception:
        try:
            return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
        except Exception:
            return None


def _serialize_date(value):
    return value.isoformat() if value else None


def _daterange_batches(start_dt: date, end_dt: date, batch_days: int):
    batches = []
    cur = start_dt
    while cur <= end_dt:
        batch_end = min(cur + timedelta(days=batch_days - 1), end_dt)
        batches.append((cur, batch_end))
        cur = batch_end + timedelta(days=1)
    return batches


def _city_stats(conn, city: str):
    city_sql = "UPPER(COALESCE(city, '')) = UPPER(?)"
    counts = conn.execute(
        f"""
        SELECT
          COUNT(*) AS row_count,
          SUM(CASE WHEN listing_number GLOB 'R*' THEN 1 ELSE 0 END) AS r_count,
          SUM(CASE WHEN listing_number GLOB 'RX-*' THEN 1 ELSE 0 END) AS rx_count,
          SUM(CASE WHEN status = 'H' THEN 1 ELSE 0 END) AS coming_soon_count
        FROM listing_details
        WHERE {city_sql}
        """,
        (city,),
    ).fetchone()

    maxima = conn.execute(
        f"""
        SELECT
          MAX(listing_date),
          MAX(status_change_date),
          MAX(under_contract_date),
          MAX(sold_date),
          MAX(withdrawn_date),
          MAX(temp_off_market_date),
          MAX(cancel_date),
          MAX(expiration_date)
        FROM listing_details
        WHERE {city_sql}
        """,
        (city,),
    ).fetchone()

    missing = {}
    for field in CRITICAL_FIELDS:
        missing[field] = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM listing_details
            WHERE {city_sql}
              AND (
                {field} IS NULL
                OR TRIM(CAST({field} AS TEXT)) = ''
              )
            """,
            (city,),
        ).fetchone()[0]

    max_dates = {col: _date_or_none(val) for col, val in zip(DATE_COLUMNS, maxima)}
    coverage_end = max([d for d in max_dates.values() if d], default=None)

    return {
        "city": city,
        "row_count": int(counts[0] or 0),
        "r_count": int(counts[1] or 0),
        "rx_count": int(counts[2] or 0),
        "coming_soon_count": int(counts[3] or 0),
        "max_dates": {k: _serialize_date(v) for k, v in max_dates.items()},
        "coverage_end": _serialize_date(coverage_end),
        "missing_counts": missing,
    }


def main():
    args = parse_args()
    cities = _parse_cities(args.cities)
    today = date.today()

    out_json = Path(args.output_json)
    out_csv = Path(args.output_csv)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(args.db_file)
    try:
        city_reports = []
        all_batches = []
        for city in cities:
            report = _city_stats(conn, city)
            coverage_end = _date_or_none(report["coverage_end"])
            next_start = coverage_end + timedelta(days=1) if coverage_end else None
            stale_days = (today - coverage_end).days if coverage_end else None
            report["next_start_date"] = _serialize_date(next_start)
            report["stale_days"] = stale_days

            if next_start and next_start <= today:
                batches = _daterange_batches(next_start, today, args.batch_days)
            else:
                batches = []
            report["recommended_batches"] = [
                {
                    "city": city,
                    "from_date": batch_start.strftime("%m/%d/%Y"),
                    "to_date": batch_end.strftime("%m/%d/%Y"),
                    "status_mode": args.status_mode,
                }
                for batch_start, batch_end in batches
            ]
            all_batches.extend(report["recommended_batches"])
            city_reports.append(report)
    finally:
        conn.close()

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "db_file": args.db_file,
        "status_mode": args.status_mode,
        "batch_days": args.batch_days,
        "cities": city_reports,
        "batch_count": len(all_batches),
    }
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "city",
                "coverage_end",
                "next_start_date",
                "stale_days",
                "from_date",
                "to_date",
                "status_mode",
                "row_count",
                "r_count",
                "rx_count",
                "coming_soon_count",
                "missing_parcel_id",
                "missing_listing_date",
                "missing_status_change_date",
                "missing_short_address",
                "missing_city",
                "missing_sold_date",
                "missing_sold_price",
            ],
        )
        writer.writeheader()
        for report in city_reports:
            batches = report["recommended_batches"] or [{}]
            for batch in batches:
                writer.writerow(
                    {
                        "city": report["city"],
                        "coverage_end": report["coverage_end"],
                        "next_start_date": report["next_start_date"],
                        "stale_days": report["stale_days"],
                        "from_date": batch.get("from_date"),
                        "to_date": batch.get("to_date"),
                        "status_mode": batch.get("status_mode"),
                        "row_count": report["row_count"],
                        "r_count": report["r_count"],
                        "rx_count": report["rx_count"],
                        "coming_soon_count": report["coming_soon_count"],
                        "missing_parcel_id": report["missing_counts"]["parcel_id"],
                        "missing_listing_date": report["missing_counts"]["listing_date"],
                        "missing_status_change_date": report["missing_counts"]["status_change_date"],
                        "missing_short_address": report["missing_counts"]["short_address"],
                        "missing_city": report["missing_counts"]["city"],
                        "missing_sold_date": report["missing_counts"]["sold_date"],
                        "missing_sold_price": report["missing_counts"]["sold_price"],
                    }
                )

    print(f"json_report={out_json}")
    print(f"csv_report={out_csv}")
    print(f"batch_count={len(all_batches)}")
    for report in city_reports:
        print(
            f"{report['city']}: coverage_end={report['coverage_end']} "
            f"next_start={report['next_start_date']} stale_days={report['stale_days']} "
            f"batches={len(report['recommended_batches'])} rows={report['row_count']}"
        )


if __name__ == "__main__":
    main()

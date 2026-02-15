"""
One-time/recurring property type normalization for listing_details.

Canonical values:
- Single Family Home
- Condo/TH/Other
"""

import os
import sqlite3

from property_type_utils import canonical_property_type


DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mls.db")


def main():
    if not os.path.exists(DB_FILE):
        print(f"Database not found: {DB_FILE}")
        return

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT rowid, listing_number, property_type FROM listing_details")
    rows = cur.fetchall()

    updates = []
    unchanged = 0
    for row in rows:
        row_id = row["rowid"]
        old_type = row["property_type"]
        new_type = canonical_property_type(old_type)
        if (old_type or None) == (new_type or None):
            unchanged += 1
            continue
        updates.append((new_type, row_id))

    for new_type, row_id in updates:
        cur.execute(
            "UPDATE listing_details SET property_type = ? WHERE rowid = ?",
            (new_type, row_id),
        )

    conn.commit()

    print("Property type normalization complete")
    print(f"  Total rows: {len(rows)}")
    print(f"  Updated: {len(updates)}")
    print(f"  Unchanged: {unchanged}")

    print("\nCurrent distribution:")
    cur.execute(
        """
        SELECT COALESCE(property_type, 'NULL') AS property_type, COUNT(*) AS cnt
        FROM listing_details
        GROUP BY COALESCE(property_type, 'NULL')
        ORDER BY cnt DESC
        """
    )
    for row in cur.fetchall():
        print(f"  {row['property_type']}: {row['cnt']}")

    conn.close()


if __name__ == "__main__":
    main()

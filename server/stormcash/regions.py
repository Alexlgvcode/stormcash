"""The four demo regions (spec §16.3) on the 40×24 town grid, west to east."""

from __future__ import annotations

import psycopg

# region_id, display_name, county, x, y, w, h
REGIONS = (
    ("west-asheville", "West Asheville", "Buncombe", 0, 0, 10, 24),
    ("asheville-downtown", "Downtown Asheville", "Buncombe", 10, 0, 10, 24),
    ("swannanoa", "Swannanoa", "Buncombe", 20, 0, 10, 24),
    ("black-mountain", "Black Mountain", "Buncombe", 30, 0, 10, 24),
)


def ensure_regions(conn: psycopg.Connection) -> None:
    """Insert the demo regions if they are missing; never overwrites edits."""
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO regions (region_id, display_name, county, x, y, w, h)
               VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (region_id) DO NOTHING""",
            REGIONS,
        )

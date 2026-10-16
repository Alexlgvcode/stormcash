"""schema.sql and spec §11.1 must stay identical (the spec is the source of truth)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_schema_sql_matches_spec_11_1():
    spec = (ROOT / "STORMCASH_BUILD_SPEC.md").read_text()
    start = spec.index("```sql\n", spec.index("### 11.1 Schema")) + len("```sql\n")
    spec_sql = spec[start : spec.index("```\n", start)]
    schema = (ROOT / "server" / "schema.sql").read_text()
    body = schema.split("\n", 2)[2]  # drop the header comment and blank line
    assert spec_sql.strip() == body.strip()

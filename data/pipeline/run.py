"""Run the whole pipeline once without Dagster: extract -> dbt build -> insights report.

cd data && .venv/bin/python -m pipeline.run
"""

import subprocess
import sys
from pathlib import Path

from . import extract, report

DATA_DIR = Path(__file__).resolve().parent.parent


def main() -> int:
    print("1/3 Extracting from PostgreSQL into the lake…")
    totals = extract.extract()
    print(f"    {sum(totals.values()):,} rows from {len(totals)} tables")
    print("2/3 Building the warehouse with dbt (models + data-quality tests)…")
    dbt = DATA_DIR / ".venv" / "bin" / "dbt"
    result = subprocess.run(
        [str(dbt), "build", "--profiles-dir", "."], cwd=DATA_DIR / "dbt", check=False
    )
    if result.returncode:
        print("dbt build failed: see the output above.", file=sys.stderr)
        return result.returncode
    print("3/3 Writing the insights report…")
    report.build()
    return 0


if __name__ == "__main__":
    sys.exit(main())

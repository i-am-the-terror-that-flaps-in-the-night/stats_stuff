"""
Convert raw NHANES .xpt downloads into .csv, in place, in extra_data/csv_data/.

Run this once after dropping new .XPT files into the folder; stats_test.py then
reads the resulting .csv files. (stats_test.py can also read .xpt directly, so
this step is optional -- it just keeps the folder uniform and faster to load.)
"""

from pathlib import Path
import pandas as pd

DATA_DIR = Path("../extra_data/csv_data")

for xpt_file in sorted(DATA_DIR.rglob("*.[xX][pP][tT]")):
    csv_file = xpt_file.with_suffix(".csv")
    try:
        df = pd.read_sas(xpt_file, format="xport")
        df.to_csv(csv_file, index=False)
        xpt_file.unlink()  # drop the raw .xpt once the .csv exists
        print(f"Converted: {xpt_file.name} -> {csv_file.name} ({len(df)} rows)")
    except Exception as e:
        print(f"Failed: {xpt_file.name}: {e}")

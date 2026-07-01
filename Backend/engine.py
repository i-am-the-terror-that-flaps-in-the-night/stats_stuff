"""
engine.py -- the backend stats engine.

Pure data logic, no console I/O: load-time cleaning of the dataframe and the
descriptive-statistics computations. app.py imports df_cleanup and DataAnalyzer
from here and exposes them over HTTP; tests/test_engine.py exercises them directly.
"""

import pandas as pd


def df_cleanup(df):
    """Coerce columns that are >=80% numeric (after stripping $ and ,) to numeric
    dtype, leaving the rest unchanged."""
    for col in df.columns:
        cleaned = df[col].astype(str).str.replace(r"[$,]", "", regex=True)
        coerced = pd.to_numeric(cleaned, errors="coerce")
        if coerced.notna().mean() >= 0.8:  # mostly numbers -> treat as numeric
            # Keep the un-parseable cells as NaN rather than imputing them with the
            # mean. Imputing would silently inflate n and shrink variance/std (the
            # filled points sit exactly on the mean), distorting the very stats this
            # tool reports. basic_analysis() drops these NaNs before summarizing.
            df[col] = coerced
    return df


class DataAnalyzer:
    def __init__(self, df):
        self.df = df

    def basic_analysis(self, column):
        series = pd.to_numeric(self.df[column], errors="coerce").dropna()

        if series.empty:
            return {"error": "No numeric values in that column."}

        modes = series.mode()
        mode_val = modes.iloc[0] if not modes.empty else float("nan")

        return {
            "column": column,
            "mean": round(float(series.mean()), 3),
            "median": float(series.median()),
            "mode": float(mode_val),
            "min": float(series.min()),
            "max": float(series.max()),
            "std": round(float(series.std()), 3),
            "variance": round(float(series.var()), 3),
        }

    def medium_analysis(self):
        # TODO: Add analysis of medium complexity
        pass

    def advanced_analysis(self):
        # TODO: Add analysis of advanced complexity
        pass

    def expert_analysis(self):
        # TODO: Add analysis of expert complexity
        pass

    def categorical_analysis(self):
        # TODO: Add analysis for categorical columns
        pass

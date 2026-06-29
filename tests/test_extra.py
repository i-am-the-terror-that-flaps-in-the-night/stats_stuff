"""
Tests for the stats engine in Backend/extra.py.

These lock in two things that are easy to regress:
  * basic_analysis() computes the expected descriptive stats and handles the
    edge cases (no numeric values, tied modes); and
  * df_cleanup() coerces mostly-numeric columns *without* imputing the gaps,
    so missing values are dropped before stats are computed -- not silently
    replaced with the mean (which would inflate n and shrink variance/std).

Run from the repo root with `uv run pytest` (pyproject puts Backend/ on the path).
"""

import math

import pandas as pd

from extra import DataAnalyzer, df_cleanup


def test_basic_analysis_numeric_column():
    """A plain numeric column reports the expected descriptive stats."""
    df = pd.DataFrame({"x": [1, 2, 3, 4, 5]})

    result = DataAnalyzer(df).basic_analysis("x")

    assert result["column"] == "x"
    assert result["mean"] == 3.0
    assert result["median"] == 3.0
    assert result["min"] == 1.0
    assert result["max"] == 5.0
    # Sample (n-1) variance of 1..5 is 2.5; std is its square root, rounded to
    # 3 decimals by basic_analysis().
    assert result["variance"] == 2.5
    assert result["std"] == round(math.sqrt(2.5), 3)
    assert "error" not in result


def test_basic_analysis_all_nan_column():
    """A column with no numeric values returns an error rather than NaN stats."""
    df = pd.DataFrame({"label": ["a", "b", "c"]})

    result = DataAnalyzer(df).basic_analysis("label")

    assert result == {"error": "No numeric values in that column."}


def test_basic_analysis_mode_tie_returns_smallest():
    """When several values tie for the mode, the smallest is reported.

    pandas' Series.mode() returns the tied values sorted ascending, and
    basic_analysis() takes the first -- so a 1-vs-2 tie resolves to 1.
    """
    df = pd.DataFrame({"x": [1, 1, 2, 2, 3]})

    result = DataAnalyzer(df).basic_analysis("x")

    assert result["mode"] == 1.0


def test_df_cleanup_keeps_missing_as_nan():
    """A mostly-numeric column is coerced, but un-parseable cells stay NaN."""
    # 9 numbers + 1 non-numeric -> 90% numeric, above the 0.8 "treat as numeric"
    # threshold, so the column is coerced.
    df = pd.DataFrame({"x": [str(i) for i in range(1, 10)] + ["n/a"]})

    cleaned = df_cleanup(df)

    assert cleaned["x"].isna().sum() == 1  # the "n/a" cell, not imputed with the mean


def test_missing_values_dropped_not_imputed():
    """Missing cells are dropped before stats, so they don't distort variance/n.

    Values 1..9 (mean 5) plus one missing cell. Dropping the gap gives the
    sample variance of nine points (60 / 8 = 7.5). If the gap were imputed at
    the mean instead, n would be 10 and the variance would shrink to 60 / 9.
    """
    df = pd.DataFrame({"x": [str(i) for i in range(1, 10)] + ["missing"]})

    result = DataAnalyzer(df_cleanup(df)).basic_analysis("x")

    assert result["mean"] == 5.0
    assert result["variance"] == 7.5

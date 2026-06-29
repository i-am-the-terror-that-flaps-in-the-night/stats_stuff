import string

import pandas as pd


def df_cleanup(df):
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


def df_stats(df):
    print(df.head())
    df.info()
    print(df.shape)
    print(" | ".join(df.columns))


def prompt_for_column(df):
    while True:
        column_name = input("Which column do you want to analyze? ").strip()
        column_name = column_name.translate(str.maketrans("", "", string.punctuation))

        if column_name not in df.columns:
            print(f"{column_name} is not an available column. \nPlease try again.")
            print("AVAILABLE COLUMNS:")
            print(" | ".join(df.columns))
            continue

        print(f"Selected the column {column_name} ...")
        return column_name


def print_series_stats(series):
    modes = series.mode()
    mode_val = modes.iloc[0] if not modes.empty else float("nan")
    print(
        f"Mean: {series.mean():.3f} \n"
        f"Median: {series.median():.3f} \n"
        f"Mode: {mode_val:.3f} \n"
        f"Min: {series.min():.3f} \n"
        f"Max: {series.max():.3f} \n"
        f"Standard Deviation: {series.std():.3f} \n"
        f"Variance: {series.var():.3f}"
    )


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
        # TODO: Add analysis of medium complexity
        pass


def main():
    df = pd.read_csv("../Data/data.csv")
    df_clean = df_cleanup(df)

    df_stats(df_clean)

    analyzer = DataAnalyzer(df_clean)
    result = analyzer.basic_analysis(column=prompt_for_column(df_clean))
    print(result)
    analyzer.medium_analysis()


if __name__ == "__main__":
    main()

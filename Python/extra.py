import string

import pandas as pd


def df_cleanup(df):
    for col in df.columns:
        cleaned = df[col].astype(str).str.replace(r"[$,]", "", regex=True)
        coerced = pd.to_numeric(cleaned, errors="coerce")
        if coerced.notna().mean() >= 0.8:  # mostly numbers -> treat as numeric
            df[col] = coerced.fillna(coerced.mean())

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

    def basic_analysis(self):
        column_name = prompt_for_column(self.df)
        series = pd.to_numeric(self.df[column_name], errors="coerce").dropna()

        if series.empty:
            print("Selected column has no numeric values to analyze.")
            return

        print_series_stats(series)

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
    df = pd.read_csv("../data/data.csv")
    df_clean = df_cleanup(df)

    df_stats(df_clean)

    analyzer = DataAnalyzer(df_clean)
    analyzer.basic_analysis()
    analyzer.medium_analysis()


if __name__ == "__main__":
    main()

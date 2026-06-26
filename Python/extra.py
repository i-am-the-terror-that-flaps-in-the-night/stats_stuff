import pandas as pd

df = pd.read_csv("../data/data.csv")


def df_cleanup(df):
    for col in df.columns:
        cleaned = df[col].astype(str).str.replace(r"[$,]", "", regex=True)
        coerced = pd.to_numeric(cleaned, errors="coerce")
        if coerced.notna().mean() >= 0.8:  # mostly numbers -> treat as numeric
            df[col] = coerced.fillna(coerced.mean())


def df_stats(df):
    print(df.head())
    df.info()
    print(df.shape)
    print(" | ".join(df.columns))


def column_analysis(df):
    while True:
        column = input("Which column do you want to analyze? ").strip().strip("!,?.;/&")

        if column not in df.columns:
            print(f"{column} is not an available column. \nPlease try again.")
            print("AVAILABLE COLUMNS:")
            print(" | ".join(df.columns))
            continue

        print(f"Selected the column {column} ...")
        break

    if column.empty:
        print("Selected column has no numeric values to analyze.")
        return

    modes = column.mode()
    mode_val = modes.iloc[0] if not modes.empty else float("nan")
    print(
        f"Mean: {column.mean():.3f} \n"
        f"Median: {column.median():.3f} \n"
        f"Mode: {mode_val:.3f} \n"
        f"Min: {column.min():.3f} \n"
        f"Max: {column.max():.3f} \n"
        f"Standard Deviation: {column.std():.3f} \n"
        f"Variance: {column.var():.3f}"
    )


def medium_analysis(df):
    # TODO: 1] ANOVA 2] Chi-Square 3] P-values
    pass


def main():
    df_cleanup(df)
    df_stats(df)
    column_analysis(df)
    medium_analysis(df)


if __name__ == "__main__":
    main()

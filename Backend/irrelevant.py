import pandas as pd

df = pd.read_csv("../Data/data.csv")

print(df.head())
print(df.shape)
print(df.describe())


def df_cleaning():
    print(df.isnull().sum())
    print(df.isnull().sum() / len(df) * 100)
    for col in df.columns:
        cleaned = df[col].astype(str).str.replace(r"[$,]", "", regex=True)
        coerced = pd.to_numeric(cleaned, errors="coerce")
        if coerced.notna().mean() >= 0.8:  # mostly numbers -> treat as numeric
            df[col] = coerced.fillna(coerced.mean())


class df_analysis:
    # TODO: Add analysis
    pass


def main():
    pass


if __name__ == "main":
    main()

"""
cli.py -- one terminal front door for all four analysis modules.

app.py is the real front door; this is the one for a developer who wants to see
what advanced_analysis() returns without booting a web server, and the one CI
uses for the two drift guards.

    python Backend/cli.py build-cohort           # rebuild the cohort CSV
    python Backend/cli.py build-cohort --check   # CI's data drift check
    python Backend/cli.py study                  # the whole study as JSON
    python Backend/cli.py train-model            # refit the ALT predictor
    python Backend/cli.py train-model --check    # CI's model drift check
    python Backend/cli.py --column BMXBMI        # a stats tier on any CSV

WHY THIS IS ITS OWN FILE
    Every one of those subcommands lives in a different module, so putting the
    dispatcher in any one of them would make that module the odd one out --
    importing its three siblings for a reason that has nothing to do with its
    statistics. Here nothing imports the CLI, the CLI imports everything, and
    the dependency arrows all still point one way.

    It also keeps argparse and the subcommand table off `import engine`, which
    is on app.py's cold-start path.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

# Nothing imports this module, so a plain module-level import of engine.py is
# safe here in a way it would not be inside cohort/study/predictor. The three
# heavier modules are still imported inside their own branches of main(): the
# study pulls in statsmodels and the predictor pulls in lightgbm, and asking for
# a column's mean should not pay for either.
try:
    from engine import DataAnalyzer, df_cleanup
except ImportError:
    from Backend.engine import DataAnalyzer, df_cleanup

# Which DataAnalyzer method each tier name maps to. app.py has the same routing
# for its JSON API (see run_analysis there); this is the terminal-side twin so a
# dev can exercise the exact same tiers without booting the web server.
_TIERS = {
    "basic": lambda analyzer, column, group: analyzer.basic_analysis(column),
    "medium": lambda analyzer, column, group: analyzer.medium_analysis(column, group),
    "advanced": lambda analyzer, column, group: analyzer.advanced_analysis(
        column, group
    ),
    "expert": lambda analyzer, column, group: analyzer.expert_analysis(column, group),
    "categorical": lambda analyzer, column, group: analyzer.categorical_analysis(
        column
    ),
}


def main(argv=None):
    """Run any analysis tier straight from the terminal and print it as JSON.

    Three other entry points hang off the same command. They live in their own
    modules -- cohort.py, study.py, predictor.py -- but share this one front
    door, because one command to remember beats four scripts to find:

        python Backend/cli.py build-cohort           # rebuild the cohort CSV
        python Backend/cli.py build-cohort --check   # CI's drift check
        python Backend/cli.py study                  # the whole study as JSON
        python Backend/cli.py train-model            # refit the ALT predictor
        python Backend/cli.py train-model --check    # CI's model drift check

    app.py is the real front door, but booting a web server just to see what
    advanced_analysis() returns is slow. This loads a CSV the same way the app
    does (Data/nhanes_analytic.csv by default), runs a tier, and prints the
    result. NHANES columns are coded (RIDAGEYR = age, BMXBMI = BMI):

        python Backend/cli.py --column BMXBMI                    # basic BMI
        python Backend/cli.py --tier medium --column BMXBMI --group RIAGENDR
        python Backend/cli.py --tier advanced --column LBXTC     # total cholesterol
        python Backend/cli.py --csv Data/data.csv --column Age   # the small demo set

    With no --column it runs the tier on every column that fits: the numeric
    columns for the number tiers, the label columns for the categorical tier.
    That split comes from analysis_utilities()'s column inventory, which is the
    same list the website builds its column picker from.

    """
    # Three sub-commands, dispatched before argparse so the tier flags below stay
    # exactly as they were.
    #
    # Each import sits INSIDE its branch, not at module scope. Two reasons, and
    # the first is the load-bearing one: cohort.py, study.py and predictor.py all
    # import from engine.py, so importing them up here would close a cycle. The
    # second is the usual one -- `import engine` is on app.py's cold-start path,
    # and the study pulls in statsmodels while the predictor pulls in lightgbm.
    # Neither belongs in the cost of asking for a column's mean.
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "build-cohort":
        from cohort import build_cohort_cli

        return build_cohort_cli(argv[1:])
    if argv and argv[0] == "train-model":
        from predictor import train_predictor_cli

        return train_predictor_cli(argv[1:])
    if argv and argv[0] == "study":
        from study import run_study

        print(json.dumps(run_study(), indent=2, default=str))
        return 0

    default_csv = (
        Path(__file__).resolve().parent.parent / "Data" / "nhanes_analytic.csv"
    )

    parser = argparse.ArgumentParser(
        description="Run the stats engine on a CSV from the terminal."
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=default_csv,
        help="CSV file to analyze (default: Data/nhanes_analytic.csv).",
    )
    parser.add_argument(
        "--tier",
        default="basic",
        choices=list(_TIERS),
        help="Which analysis tier to run (default: basic).",
    )
    parser.add_argument(
        "--column",
        help="Column to analyze. Omit to run the tier on every applicable column.",
    )
    parser.add_argument(
        "--group",
        help="Optional grouping column for the medium/advanced/expert tiers.",
    )
    args = parser.parse_args(argv)

    df = df_cleanup(pd.read_csv(args.csv))
    analyzer = DataAnalyzer(df)
    run_tier = _TIERS[args.tier]

    # One named column, or every column that fits the tier: numeric columns for
    # the number tiers, the leftover label columns for the categorical tier.
    inventory = analyzer.analysis_utilities()["columns"]
    if args.column:
        columns = [args.column]
    elif args.tier == "categorical":
        columns = inventory["categorical"]
    else:
        columns = inventory["numeric"]

    output = {column: run_tier(analyzer, column, args.group) for column in columns}
    # default=str is a safety net for any stray numpy/pandas scalar; _num() has
    # already turned the statistics themselves into plain floats and Nones.
    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    raise SystemExit(main() or 0)

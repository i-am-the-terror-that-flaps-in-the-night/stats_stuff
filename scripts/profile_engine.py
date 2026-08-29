#!/usr/bin/env python
"""
Time every part of the engine, so optimizing goes where the seconds actually are.

    python scripts/profile_engine.py                      # benchmark everything
    python scripts/profile_engine.py study                # one suite
    python scripts/profile_engine.py --list               # what can be run
    python scripts/profile_engine.py --repeat 3           # fewer runs, rougher
    python scripts/profile_engine.py --profile study:dose-response
    python scripts/profile_engine.py --memory             # bytes, not seconds
    python scripts/profile_engine.py --memory --profile study:risk-score

The suites map to the four things the engine spends time on:

    boot     import cost, measured in a fresh interpreter -- Render's free tier
             pays this on every cold start, so it is a user-visible number
    data     reading CSVs and deriving the cohort
    study    each protocol step, then the whole study end to end
    tiers    the five DataAnalyzer tiers the website calls
    figures  matplotlib rendering (slow; only runs if you name it)

WHAT THE NUMBERS ARE
    Ten runs per case by default, reported as the MEAN. A mean uses every run
    instead of throwing nine of them away, which is what makes it steadier than
    any single measurement -- but it is also the statistic an outlier drags
    furthest, and a benchmark on a laptop collects outliers from things that
    have nothing to do with the code: a GC pass, another process taking the
    core, the CPU clocking itself down. Hence three columns rather than one:

      mean  the headline, over --repeat runs.
      sd    how far those runs disagreed. Small beside the mean means the mean
            is a real number; comparable to the mean means the machine was busy
            and the row is worth re-running before anyone optimizes against it.
      best  the fastest run -- the closest thing available to the cost of the
            code with the operating system's contribution subtracted. A wide
            gap between best and mean is noise, not work.

    One extra run happens first and is thrown away. A first call pays for
    things a second one does not -- pandas filling its dispatch caches, the
    allocator growing a fresh arena, pages being faulted in -- and those are
    per-process costs, not per-call ones. Left in a ten-run mean they would
    quietly inflate every small case by a tenth of the cold penalty. (The boot
    suite is indifferent to this: each of its runs is a brand new interpreter,
    so none of them is ever warm, which is the entire point of that suite.)

MEMORY (--memory)
    The same cases, measured in bytes. This matters here for a reason specific
    to the engine: nearly everything is lru_cached and nothing is ever evicted,
    so memory a step allocates on its first call is memory the process holds for
    as long as it runs. On Render's free tier that budget is 512 MB, and the
    question "which step is expensive" has a memory answer as well as a time one.

    Three numbers per case, because no single one is honest on its own:

      py-peak   The high-water mark of PYTHON-level allocation during the case,
                from tracemalloc. Exact for objects, and an undercount for
                pandas and numpy, whose data buffers are allocated outside the
                Python allocator and are invisible to it.
      retained  Python memory still allocated after the case and a gc pass.
                This is the lru_cache figure -- what the process will hold for
                the rest of its life -- and the caches hold dicts of floats and
                strings, which is exactly what tracemalloc measures well.
      rss-new   How far this case pushed the process's ALL-TIME high-water
                mark (getrusage). The counterweight to the other two: it is what
                catches the transient a big read_csv allocates and frees, which
                lives outside the Python allocator and so is invisible above.

                Read it as "did this case set a new record", not "what did this
                case cost". A high-water mark only moves upward, so once one
                expensive case has raised it every later case that stays under
                it reports zero -- truthfully, and about the wrong question. The
                column is informative for the biggest case in a run and mostly
                silent after it.

    `retained` is deliberately NOT an RSS delta. RSS does not fall when Python
    frees an object -- the allocator keeps the arena -- so an RSS-based retained
    figure cannot tell a cache apart from a temporary, and reported 43 MB
    "retained" for reading a CSV that was discarded on the next line.

    Memory mode runs each case ONCE regardless of --repeat. Repeating corrupts
    `retained`: the second run finds the cache already warm and reports nothing
    retained, for a step that in fact costs everything the first run said.

WHY EACH REPEAT RESETS THE CACHES
    run_step, run_study and headline are lru_cached, so a naive second call
    costs nothing and the benchmark would report a lie. Before every timed run
    this clears every cache in the module EXCEPT load_cohort, which stays warm
    on purpose: reading the cohort CSV is measured once in the `data` suite, and
    charging it again to all eleven study steps would bury the step that is
    genuinely slow under eleven copies of the same file read.
"""

from __future__ import annotations

import argparse
import cProfile
import gc
import os
import pstats
import resource
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Backend"))

import engine  # noqa: E402


# ----------------------------------------------------------------------
# THE CASES
# ----------------------------------------------------------------------
# A case is a zero-argument callable. Normally it is timed by the clock around
# it; if it returns a float, that float is used as its elapsed time instead --
# which is how the boot suite reports the import cost of a subprocess without
# also charging it for spawning the subprocess.


# Marks a case that is a component of another case -- `import-pandas` happens
# inside `import-engine`, `read-raw-csv` inside `build-cohort`. Worth timing to
# see where a slow case spends itself, but adding it to the total would count
# the same milliseconds twice, so the table prints it and skips it in the sum.
PART = "part"


def _import_cost(module: str):
    """Seconds to import `module` in an interpreter that has never seen it."""
    code = f"import time;t=time.perf_counter();import {module};print(time.perf_counter()-t)"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "Backend")},
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip().splitlines()[-1])
    return float(proc.stdout)


def _tier_cases():
    """The five DataAnalyzer tiers on the cohort, ALT grouped by sex."""
    frame = engine.df_cleanup(engine.pd.read_csv(engine.COHORT_CSV))
    analyzer = engine.DataAnalyzer(frame)
    return [
        ("basic", lambda: analyzer.basic_analysis("ALT")),
        ("medium", lambda: analyzer.medium_analysis("ALT", "Sex")),
        ("advanced", lambda: analyzer.advanced_analysis("ALT", "Sex")),
        ("expert", lambda: analyzer.expert_analysis("ALT", "Sex")),
        ("categorical", lambda: analyzer.categorical_analysis("Sex")),
        ("utilities", lambda: analyzer.analysis_utilities()),
    ]


def _figure_case():
    frame = engine.df_cleanup(engine.pd.read_csv(engine.COHORT_CSV))
    analyzer = engine.DataAnalyzer(frame)
    out = tempfile.mkdtemp(prefix="engine-figures-")
    return [("figure-production", lambda: analyzer.figure_production(out))]


def build_suites(wanted: set[str]) -> dict[str, list]:
    """Only build the suites asked for -- constructing `tiers` reads a CSV, and
    a run of `boot` alone should not pay for that."""
    suites: dict[str, list] = {}

    if "boot" in wanted:
        # statsmodels and matplotlib are imported inside the methods that need
        # them, so they are not part of `import engine` -- they are billed to
        # whichever call touches them first. Measuring each in its own
        # interpreter is the only way to see that cost; inside one benchmark
        # process the second caller onwards imports nothing and looks fast.
        suites["boot"] = [
            ("import-engine (cold start)", lambda: _import_cost("engine")),
            ("import-pandas", lambda: _import_cost("pandas"), PART),
            ("import-scipy-stats", lambda: _import_cost("scipy.stats"), PART),
            ("first-use-statsmodels", lambda: _import_cost("statsmodels.api")),
            ("first-use-matplotlib", lambda: _import_cost("matplotlib.pyplot")),
        ]

    if "data" in wanted:
        # df_cleanup gets a fresh copy each run so the read is not timed twice
        # and so a mutating pass cannot make later repeats look cheap.
        raw_cohort = engine.pd.read_csv(engine.COHORT_CSV)
        cases = [
            ("load-cohort", _cold_load_cohort),
            ("read-cohort-csv", lambda: engine.pd.read_csv(engine.COHORT_CSV), PART),
            ("df-cleanup", lambda: engine.df_cleanup(raw_cohort.copy())),
            (
                "analysis-frame",
                lambda: engine.analysis_frame(
                    ["ALT", "TotalSugars", "Age", "Sex", "BMI"]
                ),
            ),
        ]
        if engine.raw_merge_available():  # a stub in production (Git LFS)
            cases += [
                ("build-cohort", engine.build_cohort),
                ("read-raw-csv", lambda: engine.pd.read_csv(engine.RAW_CSV), PART),
            ]
        suites["data"] = cases

    if "study" in wanted:
        suites["study"] = [
            (name, (lambda n: lambda: engine.run_step(n))(name))
            for name in engine.STEP_NAMES
        ] + [("run_study() end to end", engine.run_study, PART)]

    if "tiers" in wanted:
        suites["tiers"] = _tier_cases()

    if "figures" in wanted:
        suites["figures"] = _figure_case()

    return suites


def _cold_load_cohort():
    """load_cohort() with its own cache dropped -- the real first-call cost."""
    engine.load_cohort.cache_clear()
    return engine.load_cohort()


def warm_lazy_imports() -> None:
    """Import statsmodels and matplotlib before anything is timed.

    The engine imports them inside the methods that need them, so without this
    whichever case runs first absorbs ~900 ms of import time and looks slow for
    reasons that have nothing to do with its statistics. That cost is real, but
    it is a boot cost, and the boot suite prices it honestly by importing each
    one in its own fresh interpreter.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot  # noqa: F401
    import statsmodels.api  # noqa: F401


def reset():
    """Drop every memo in the module except the cohort itself."""
    for value in vars(engine).values():
        clear = getattr(value, "cache_clear", None)
        if clear is not None and value is not engine.load_cohort:
            clear()
    engine.load_cohort()  # keep the cohort warm; `data` already priced it


# ----------------------------------------------------------------------
# RUNNING AND REPORTING
# ----------------------------------------------------------------------


def iter_cases(suites: dict[str, list]):
    """(suite, name, callable, counted) for every case, 2- or 3-tuple alike."""
    for suite, cases in suites.items():
        for entry in cases:
            name, case = entry[0], entry[1]
            yield suite, name, case, len(entry) < 3


def measure(case, repeat: int, tick=None) -> list[float]:
    """Time a case `repeat` times, after one warm-up run that is discarded.

    See WHAT THE NUMBERS ARE in the module docstring for why the warm-up is
    thrown away rather than averaged in. `tick` is called with the number of
    runs finished so far (0 for the warm-up) so a slow suite can show progress
    instead of looking hung.
    """
    reset()
    case()
    if tick:
        tick(0)

    times = []
    for index in range(repeat):
        reset()
        start = time.perf_counter()
        reported = case()
        elapsed = time.perf_counter() - start
        times.append(reported if isinstance(reported, float) else elapsed)
        if tick:
            tick(index + 1)
    return times


def spread(times: list[float]) -> float:
    """Standard deviation of the runs, or zero when there is only one."""
    return statistics.stdev(times) if len(times) > 1 else 0.0


def report(results: list[tuple[str, list[float] | str, bool]], repeat: int) -> None:
    """One table, slowest first, because that is the reading order for the
    question this tool exists to answer."""
    timed = [(n, t, c) for n, t, c in results if not isinstance(t, str)]
    failed = [(n, t) for n, t, _ in results if isinstance(t, str)]

    if not timed:
        print("nothing ran")
    else:
        # Shares are means over a mean total, so the column adds to 100% -- a
        # table mixing means with a total of minimums would not.
        total = sum(statistics.fmean(t) for _, t, counted in timed if counted)
        width = max(len(name) for name, _, _ in timed)
        print(
            f"\n{'case':<{width}}  {'mean':>10}  {'sd':>9}  {'best':>10}  {'share':>6}"
        )
        print("-" * (width + 43))
        for name, t, counted in sorted(timed, key=lambda r: -statistics.fmean(r[1])):
            mean = statistics.fmean(t)
            share = mean / total if total and counted else 0
            cell = f"{share:>6.1%}" if counted else "    --"
            print(
                f"{name:<{width}}  {mean * 1000:>8.1f}ms  {spread(t) * 1000:>7.1f}ms  "
                f"{min(t) * 1000:>8.1f}ms  {cell} {'#' * round(share * 20)}"
            )
        print(f"\ntotal of the counted cases: {total * 1000:.0f}ms")
        print(
            f"mean of {repeat} run{'s' if repeat != 1 else ''} per case, "
            "after one discarded warm-up."
        )
        print("rows with -- are a component of another row, so they are not summed.")

        # A mean is only worth quoting when the runs behind it agreed. Rather
        # than leave that to whoever reads the sd column, say so outright.
        noisy = [
            name
            for name, t, _ in timed
            if statistics.fmean(t) > 0 and spread(t) > 0.25 * statistics.fmean(t)
        ]
        if noisy:
            print("\nnoisy -- sd above a quarter of the mean, so treat these as rough:")
            for name in noisy:
                print(f"  {name}")

    for name, error in failed:
        print(f"FAILED  {name}: {error}")


def profile_one(suites: dict[str, list], target: str) -> int:
    """cProfile a single case and print the functions it spent the time in."""
    for suite, name, case, _ in iter_cases(suites):
        if target in (name, f"{suite}:{name}"):
            reset()
            profiler = cProfile.Profile()
            profiler.runcall(case)
            stats = pstats.Stats(profiler).strip_dirs()
            print(f"\n=== {suite}:{name} -- by cumulative time ===")
            stats.sort_stats("cumulative").print_stats(18)
            print(f"=== {suite}:{name} -- by time in the function itself ===")
            stats.sort_stats("tottime").print_stats(12)
            return 0
    print(f"no such case: {target!r} (try --list)")
    return 1


# ----------------------------------------------------------------------
# MEMORY
# ----------------------------------------------------------------------


def rss_bytes() -> int:
    """This process's resident set size, right now.

    Shelled out to ps rather than read from psutil, which is not a dependency of
    this project and is not worth becoming one for three numbers. ps reports
    kilobytes on both macOS and Linux.
    """
    out = subprocess.run(
        ["ps", "-o", "rss=", "-p", str(os.getpid())], capture_output=True, text=True
    )
    return int(out.stdout.strip() or 0) * 1024


def rss_high_water() -> int:
    """The largest RSS this process has ever reached.

    getrusage's ru_maxrss, whose UNIT is not portable: bytes on macOS, kilobytes
    on Linux. Getting this wrong scales every memory number by 1024, which looks
    plausible enough to go unnoticed, so it is handled explicitly.
    """
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return raw if sys.platform == "darwin" else raw * 1024


class Memory(NamedTuple):
    """What one case cost, from three vantage points. See the module docstring."""

    py_peak: int
    retained: int
    rss_peak: int


def measure_memory(case) -> Memory:
    """Run a case once and account for what it allocated and what it kept.

    tracemalloc must already be running -- memory mode starts it once, before
    anything is built. It can only account for allocations made while it is on,
    so starting it per case would make every cache look free: the cached object
    was allocated before the clock started, and only its absence on a later
    clear would ever be visible.
    """
    reset()
    gc.collect()
    tracemalloc.reset_peak()
    before_py = tracemalloc.get_traced_memory()[0]
    before_hwm = rss_high_water()

    case()

    _, peak_py = tracemalloc.get_traced_memory()
    # Collect before reading the retained figure: without it, `retained` would
    # include every temporary the case made and merely stopped referencing,
    # which is the opposite of what the column claims to measure.
    gc.collect()
    after_py = tracemalloc.get_traced_memory()[0]
    return Memory(
        peak_py - before_py, after_py - before_py, rss_high_water() - before_hwm
    )


def human(size: int) -> str:
    """Bytes as something a person can compare at a glance."""
    if abs(size) < 1024:
        return f"{size} B"
    if abs(size) < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def report_memory(results: list[tuple[str, Memory | str, bool]]) -> None:
    """One table, largest retained first -- the number that decides the plan."""
    measured = [(n, m) for n, m, _ in results if not isinstance(m, str)]
    failed = [(n, m) for n, m, _ in results if isinstance(m, str)]

    if not measured:
        print("nothing ran")
    else:
        width = max(len(name) for name, _ in measured)
        print(
            f"\n{'case':<{width}}  {'py-peak':>10}  {'retained':>10}  {'rss-new':>10}"
        )
        print("-" * (width + 38))
        for name, m in sorted(measured, key=lambda r: -r[1].retained):
            print(
                f"{name:<{width}}  {human(m.py_peak):>10}  "
                f"{human(m.retained):>10}  {human(m.rss_peak):>10}"
            )
        print(f"\nprocess resident set size now: {human(rss_bytes())}")
        print(f"process all-time high-water mark: {human(rss_high_water())}")
        print(f"of which the engine's caches hold: {human(cache_footprint())}")
        print(
            "\npy-peak and retained are Python-allocator figures and undercount\n"
            "pandas and numpy data buffers; rss-new is what catches those -- but\n"
            "only for the case that sets the record. A high-water mark never\n"
            "falls, so a later case that stays under it reports 0 B."
        )

    for name, error in failed:
        print(f"FAILED  {name}: {error}")


def cache_footprint() -> int:
    """How much the engine's memoization is actually holding.

    Measured rather than inferred: drop every lru_cache in the module, including
    the cohort, and see how much traced memory goes away. Read through
    tracemalloc rather than RSS for the reason given in the module docstring --
    RSS would report zero here, because freeing an object does not hand the page
    back to the operating system.
    """
    gc.collect()
    before = tracemalloc.get_traced_memory()[0]
    for value in vars(engine).values():
        clear = getattr(value, "cache_clear", None)
        if clear is not None:
            clear()
    gc.collect()
    return max(0, before - tracemalloc.get_traced_memory()[0])


def profile_memory(suites: dict[str, list], target: str) -> int:
    """The memory analogue of cProfile: which lines allocated, and how much."""
    for suite, name, case, _ in iter_cases(suites):
        if target in (name, f"{suite}:{name}"):
            reset()
            gc.collect()
            tracemalloc.start()
            before = tracemalloc.take_snapshot()
            case()
            after = tracemalloc.take_snapshot()
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            # Compared against a snapshot taken just before the call, so the
            # cohort and the imports -- allocated long ago and still live -- do
            # not drown the handful of lines this case is responsible for.
            print(f"\n=== {suite}:{name} -- allocations by line ===")
            print(f"python peak during the call: {human(peak)}\n")
            for stat in after.compare_to(before, "lineno")[:18]:
                frame = stat.traceback[0]
                where = f"{Path(frame.filename).name}:{frame.lineno}"
                print(
                    f"{human(stat.size_diff):>10}  {stat.count_diff:>7} blocks  {where}"
                )
            return 0
    print(f"no such case: {target!r} (try --list)")
    return 1


ALL_SUITES = ["boot", "data", "study", "tiers", "figures"]
DEFAULT_SUITES = [s for s in ALL_SUITES if s != "figures"]  # figures is slow


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument(
        "suites",
        nargs="*",
        choices=ALL_SUITES,
        default=[],
        help="suites to run (default: all but figures)",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=10,
        help="timed runs to average per case (default: 10)",
    )
    parser.add_argument(
        "--profile", metavar="CASE", help="cProfile one case instead of benchmarking"
    )
    parser.add_argument(
        "--memory",
        action="store_true",
        help="measure bytes instead of seconds (runs each case once)",
    )
    parser.add_argument(
        "--no-raw",
        action="store_true",
        help="hide the raw merge, the way a Render deploy sees it",
    )
    parser.add_argument("--list", action="store_true", help="list the cases and exit")
    args = parser.parse_args(argv)

    # Production does not have Data/nhanes_analytic.csv -- it lives in Git LFS
    # and the deploy never fetches it, so what sits at that path there is the
    # 133-byte pointer stub git leaves behind. Locally the real 17 MB file is
    # usually present, and the difference is not small: with it, build_cohort()
    # parses 412 columns and cohort_attrition() rebuilds from them.
    #
    # The stub is written out rather than pointing at a path that does not exist,
    # because "absent" and "present but not the data" are different states and
    # only one of them is the deploy. Getting that wrong is what hid a 500 on
    # /api/study for as long as it was hidden.
    if args.no_raw:
        stub = Path(tempfile.mkdtemp(prefix="engine-lfs-")) / "nhanes_analytic.csv"
        stub.write_text(engine.LFS_POINTER_HEAD.decode() + "\noid sha256:0\nsize 0\n")
        engine.RAW_CSV = stub
        engine.cohort_attrition.cache_clear()

    # Started before the suites are built, because building `data` and `tiers`
    # reads CSVs whose frames must be accounted for like everything else.
    if args.memory and not args.profile:
        tracemalloc.start()

    wanted = set(args.suites or DEFAULT_SUITES)
    if args.profile:  # a case name is enough; build every suite so it resolves
        wanted = set(ALL_SUITES)
    suites = build_suites(wanted)

    if args.list:
        for suite, name, _, _ in iter_cases(suites):
            print(f"{suite}:{name}")
        return 0

    if wanted & {"study", "tiers", "figures"} or args.profile:
        warm_lazy_imports()

    if args.profile:
        return (
            profile_memory(suites, args.profile)
            if args.memory
            else profile_one(suites, args.profile)
        )

    if engine.raw_merge_available():
        print("note: the raw merge is present, so build_cohort() reads 17 MB here.")
        print("      Production has only the LFS stub; --no-raw measures that.")

    if args.memory:
        # The boot suite measures other interpreters, so its memory is theirs
        # and not ours -- an import cost of 0 bytes retained here would be a
        # true number about a completely uninteresting thing.
        suites.pop("boot", None)

    results = []
    for suite, name, case, counted in iter_cases(suites):
        # Progress goes to stderr so piping the table into a file stays clean.
        # It counts the runs because averaging ten of them takes long enough
        # that a single static line looks like a hang.
        def note(stage: str, suite=suite, name=name) -> None:
            print(
                f"running {suite}:{name} [{stage}] ...".ljust(72),
                end="\r",
                file=sys.stderr,
            )

        def tick(done: int) -> None:
            note("warm-up" if done == 0 else f"{done}/{args.repeat}")

        try:
            if args.memory:  # measured once; a repeat would empty `retained`
                note("once")
                outcome = measure_memory(case)
            else:
                tick(0)
                outcome = measure(case, args.repeat, tick)
        except Exception as error:  # a broken case should not stop the rest
            outcome = f"{type(error).__name__}: {error}"
        results.append((f"{suite}:{name}", outcome, counted))
    print(" " * 72, end="\r", file=sys.stderr)

    if args.memory:
        report_memory(results)
    else:
        report(results, args.repeat)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

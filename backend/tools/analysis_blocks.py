"""
The analysis menu (stage S4) and its implementations.

An analysis plan may only use blocks defined here, with parameters checked
against each block's spec, and a decision rule may only reference a block's
declared outputs. The model picks and parameterises blocks; it never writes
analysis code. On 2026-09-13 the local 8b model, asked to write the analysis
itself, produced an evaluate.py of repeated imports of functions that do not
exist and a train.py that used the group index as the number of years.

This file is copied into each session's experiment folder and run there, so it
depends only on numpy, pandas and scipy (statsmodels has no Python 3.14 wheel
in the project environment). Every block is observational: none supports a
causal claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd
from scipy import stats

STATS = ("slope", "recent_slope", "last_value", "mean_value", "recent_mean")


@dataclass(frozen=True)
class Param:
    name: str
    kind: str            # indicator | selector | pair | slice | int | float | choice
    required: bool = True
    default: object = None
    choices: tuple = ()
    help: str = ""


@dataclass(frozen=True)
class BlockSpec:
    name: str
    summary: str
    params: tuple
    outputs: tuple
    run: Callable = field(repr=False, compare=False, default=None)

    def param(self, name: str) -> Param | None:
        return next((p for p in self.params if p.name == name), None)


# --- statistics helpers ---------------------------------------------------------

def _trend(t: np.ndarray, y: np.ndarray, confidence: float) -> tuple[float, float, float]:
    """OLS slope of y on t with its confidence interval; NaN with fewer than 3 points."""
    t, y = np.asarray(t, dtype=float), np.asarray(y, dtype=float)
    n = len(t)
    if n < 3:
        return np.nan, np.nan, np.nan
    if np.ptp(y) == 0:
        return 0.0, 0.0, 0.0
    x = t - t.mean()
    sxx = float((x ** 2).sum())
    if sxx == 0:
        return np.nan, np.nan, np.nan
    slope = float((x * (y - y.mean())).sum() / sxx)
    resid = y - (y.mean() + slope * x)
    se = float(np.sqrt((resid ** 2).sum() / (n - 2) / sxx))
    half = float(stats.t.ppf(0.5 + confidence / 2, n - 2)) * se
    return slope, slope - half, slope + half


def _series(df: pd.DataFrame, keys: list[str], window: int, confidence: float) -> pd.DataFrame:
    """One row per series with full-period and recent-window statistics."""
    rows = []
    for key, part in df.groupby(keys, sort=True):
        part = part.sort_values("time")
        t, y = part["time"].to_numpy(), part["value"].to_numpy(dtype=float)
        recent = part[part["time"] > t.max() - window]
        slope, lo, hi = _trend(t, y, confidence)
        r_slope, r_lo, r_hi = _trend(recent["time"].to_numpy(), recent["value"].to_numpy(dtype=float), confidence)
        key = key if isinstance(key, tuple) else (key,)
        rows.append({**dict(zip(keys, key)), "n_years": len(part), "first_year": int(t.min()),
                     "last_year": int(t.max()), "slope": slope, "slope_ci_low": lo, "slope_ci_high": hi,
                     "recent_slope": r_slope, "recent_ci_low": r_lo, "recent_ci_high": r_hi,
                     "recent_mean": float(recent["value"].mean()), "last_value": float(y[-1]),
                     "mean_value": float(y.mean())})
    return pd.DataFrame(rows)


def _eligible(series: pd.DataFrame, stat: str, min_years: int) -> tuple[pd.DataFrame, int]:
    """Drop series too short for a slope statistic. Returns (kept, number dropped)."""
    if stat in ("slope", "recent_slope"):
        kept = series[(series["n_years"] >= min_years) & series[stat].notna()]
    else:
        kept = series[series[stat].notna()]
    return kept, len(series) - len(kept)


def _bootstrap_ci(values: np.ndarray, statistic: Callable, n_boot: int, seed: int, confidence: float):
    rng = np.random.default_rng(seed)
    values = np.asarray(values)
    boots = np.array([statistic(values[rng.integers(0, len(values), len(values))]) for _ in range(n_boot)])
    alpha = 1 - confidence
    return float(np.nanquantile(boots, alpha / 2)), float(np.nanquantile(boots, 1 - alpha / 2))


def _wilson(k: int, n: int, confidence: float) -> tuple[float, float]:
    if n == 0:
        return np.nan, np.nan
    z = float(stats.norm.ppf(0.5 + confidence / 2))
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return float(centre - half), float(centre + half)


def _threshold_note(series: pd.DataFrame, threshold: float) -> list[str]:
    """
    Warn when the classification threshold is small next to the year-to-year
    movement in this data, so noise alone lands series in rising or reversed
    (2026-09-20: a plan used 0.05 percentage points per year).
    """
    slopes = series["recent_slope"].abs().dropna()
    if slopes.empty:
        return []
    typical = float(slopes.median())
    if typical > 0 and threshold < 0.25 * typical:
        return [f"threshold {threshold:g} is well below the typical recent change in this data "
                f"(median |slope| = {typical:.3g}), so most series are classified as rising or reversed"]
    return []


def _classify(row, threshold: float, saturation: float | None) -> str:
    if saturation is not None and row["recent_mean"] >= saturation:
        return "saturated"
    if np.isnan(row["recent_slope"]):
        return "insufficient"
    if row["recent_slope"] > threshold and row["recent_ci_low"] > 0:
        return "rising"
    if row["recent_slope"] < -threshold and row["recent_ci_high"] < 0:
        return "reversed"
    return "stalled"


def _clean(value):
    if isinstance(value, (np.floating, float)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, np.integer):
        return int(value)
    return value


def _result(outputs: dict, rows: pd.DataFrame | None = None, notes: list[str] | None = None) -> dict:
    return {"outputs": {k: _clean(v) for k, v in outputs.items()},
            "rows": [] if rows is None else [{k: _clean(v) for k, v in r.items()} for r in rows.to_dict("records")],
            "notes": notes or []}


def _codes(selector: str) -> list[str]:
    return [c.strip() for c in selector.partition(":")[2].split(",") if c.strip()]


# --- blocks ---------------------------------------------------------------------

def series_trend(load, p):
    df = load(p["indicator"], split=p.get("split"))
    keys = ["unit"] + (["split"] if p.get("split") else [])
    series = _series(df, keys, p["window"], p["confidence"])
    kept, dropped = _eligible(series, "slope", p["min_years"])
    n = len(kept)
    return _result({
        "n_series": n, "n_units": kept["unit"].nunique() if n else 0,
        "mean_slope": kept["slope"].mean() if n else np.nan,
        "median_slope": kept["slope"].median() if n else np.nan,
        "share_rising_ci": (kept["slope_ci_low"] > 0).mean() if n else np.nan,
        "share_falling_ci": (kept["slope_ci_high"] < 0).mean() if n else np.nan,
    }, kept, [f"{dropped} series dropped with fewer than {p['min_years']} years"] if dropped else [])


def trajectory_class(load, p):
    df = load(p["indicator"], split=p.get("split"))
    keys = ["unit"] + (["split"] if p.get("split") else [])
    series = _series(df, keys, p["window"], p["confidence"])
    kept, dropped = _eligible(series, "recent_slope", p["min_years"])
    kept = kept.assign(trajectory=[_classify(r, p["threshold"], p.get("saturation")) for _, r in kept.iterrows()])
    n = len(kept)
    share = lambda c: (kept["trajectory"] == c).mean() if n else np.nan
    return _result({"n_series": n, "share_rising": share("rising"), "share_stalled": share("stalled"),
                    "share_reversed": share("reversed"), "share_saturated": share("saturated")},
                   kept, ([f"{dropped} series dropped with fewer than {p['min_years']} years"] if dropped else [])
                   + _threshold_note(kept, p["threshold"]))


def _paired_series(load, p):
    first, second = _codes(p["pair"])
    df = load(p["indicator"], split=p["pair"])
    series = _series(df, ["unit", "split"], p["window"], p["confidence"])
    wide = series.pivot(index="unit", columns="split")
    wide = wide.dropna(subset=[("n_years", first), ("n_years", second)])
    return wide, first, second


def paired_difference(load, p):
    wide, first, second = _paired_series(load, p)
    stat, notes = p["stat"], []
    if stat in ("slope", "recent_slope"):
        ok = (wide[("n_years", first)] >= p["min_years"]) & (wide[("n_years", second)] >= p["min_years"])
        if (~ok).any():
            notes.append(f"{int((~ok).sum())} units dropped with fewer than {p['min_years']} years")
        wide = wide[ok]
    if p.get("exclude_at_or_above") is not None:
        cap = p["exclude_at_or_above"]
        ok = (wide[("recent_mean", first)] < cap) & (wide[("recent_mean", second)] < cap)
        notes.append(f"{int((~ok).sum())} units excluded with a recent mean at or above {cap}")
        wide = wide[ok]
    rows = pd.DataFrame({f"{stat}_{first}": wide[(stat, first)], f"{stat}_{second}": wide[(stat, second)]})
    rows["difference"] = rows.iloc[:, 0] - rows.iloc[:, 1]
    rows = rows.dropna().reset_index().rename(columns={"index": "unit"})
    diff = rows["difference"].to_numpy(dtype=float)
    n = len(diff)
    if n < 3:
        return _result({"n_units": n}, notes=notes + ["fewer than 3 units: no estimate"])
    sd = diff.std(ddof=1)
    nonzero = diff[diff != 0]
    low, high = _bootstrap_ci(diff, np.mean, p["bootstrap"], p["seed"], p["confidence"])
    return _result({
        "mean": diff.mean(), "median": np.median(diff), "ci_low": low, "ci_high": high,
        "t_p": stats.ttest_1samp(diff, 0.0).pvalue,
        "wilcoxon_p": stats.wilcoxon(nonzero).pvalue if len(nonzero) >= 3 else np.nan,
        "cohens_d": diff.mean() / sd if sd > 0 else np.nan,
        "share_first_greater": (diff > 0).mean(), "n_units": n,
    }, rows, notes)


def class_agreement(load, p):
    wide, first, second = _paired_series(load, p)
    ok = (wide[("n_years", first)] >= p["min_years"]) & (wide[("n_years", second)] >= p["min_years"])
    wide = wide[ok]
    classes = {}
    for code in (first, second):
        part = wide.xs(code, axis=1, level=1)
        classes[code] = [_classify(r, p["threshold"], p.get("saturation")) for _, r in part.iterrows()]
    table = pd.DataFrame({"unit": wide.index, first: classes[first], second: classes[second]})
    n = len(table)
    differ = int((table[first] != table[second]).sum())
    low, high = _wilson(differ, n, p["confidence"])
    return _result({"disagreement_share": differ / n if n else np.nan, "ci_low": low, "ci_high": high,
                    "n_units": n}, table, _threshold_note(wide.xs(first, axis=1, level=1), p["threshold"]))


def group_comparison(load, p):
    first, second = _codes(p["groups"])
    df = load(p["indicator"], split=p.get("slice"), attribute=p["groups"])
    series = _series(df, ["unit", "attribute"], p["window"], p["confidence"])
    kept, dropped = _eligible(series, p["stat"], p["min_years"])
    a = kept.loc[kept["attribute"] == first, p["stat"]].to_numpy(dtype=float)
    b = kept.loc[kept["attribute"] == second, p["stat"]].to_numpy(dtype=float)
    if len(a) < 3 or len(b) < 3:
        return _result({"n_first": len(a), "n_second": len(b)}, notes=["fewer than 3 units in a group: no estimate"])
    rng = np.random.default_rng(p["seed"])
    boots = [rng.choice(a, len(a)).mean() - rng.choice(b, len(b)).mean() for _ in range(p["bootstrap"])]
    alpha = 1 - p["confidence"]
    return _result({"mean_first": a.mean(), "mean_second": b.mean(), "difference": a.mean() - b.mean(),
                    "ci_low": np.quantile(boots, alpha / 2), "ci_high": np.quantile(boots, 1 - alpha / 2),
                    "mannwhitney_p": stats.mannwhitneyu(a, b).pvalue, "n_first": len(a), "n_second": len(b)},
                   kept, [f"{dropped} series dropped"] if dropped else [])


CLASSES = ("rising", "stalled", "reversed", "saturated", "not_rising")


def trajectory_group_comparison(load, p):
    """
    Classify countries by the recent trajectory of `indicator` (total), then
    compare a per-country statistic of `indicator_y` between two classes. With
    `pair_y` the statistic is the within-country difference first minus second.
    """
    base = _series(load(p["indicator"]), ["unit"], p["window"], p["confidence"])
    base, _ = _eligible(base, "recent_slope", p["min_years"])
    labels = {r["unit"]: _classify(r, p["threshold"], p.get("saturation")) for _, r in base.iterrows()}

    stat = p["stat_y"]
    if p.get("pair_y"):
        first_code, second_code = _codes(p["pair_y"])
        ys = _series(load(p["indicator_y"], split=p["pair_y"]), ["unit", "split"], p["window"], p["confidence"])
        ys, _ = _eligible(ys, stat, p["min_years"])
        wide = ys.pivot(index="unit", columns="split", values=stat).dropna()
        y = wide[first_code] - wide[second_code]
    else:
        ys = _series(load(p["indicator_y"], split=p.get("slice_y")), ["unit"], p["window"], p["confidence"])
        ys, _ = _eligible(ys, stat, p["min_years"])
        y = ys.set_index("unit")[stat]

    def members(cls):
        wanted = {"stalled", "reversed"} if cls == "not_rising" else {cls}
        return [u for u, lab in labels.items() if lab in wanted and u in y.index]

    first, second = (c.strip() for c in p["classes"].split(","))
    a, b = y[members(first)].to_numpy(dtype=float), y[members(second)].to_numpy(dtype=float)
    rows = pd.DataFrame({"unit": list(labels), "class": list(labels.values())})
    notes = _threshold_note(base, p["threshold"])
    if len(a) < 3 or len(b) < 3:
        return _result({"n_first": len(a), "n_second": len(b)}, rows,
                       notes + ["fewer than 3 countries in a class: no estimate"])
    rng = np.random.default_rng(p["seed"])
    boots = [rng.choice(a, len(a)).mean() - rng.choice(b, len(b)).mean() for _ in range(p["bootstrap"])]
    alpha = 1 - p["confidence"]
    return _result({"mean_first": a.mean(), "mean_second": b.mean(), "difference": a.mean() - b.mean(),
                    "ci_low": np.quantile(boots, alpha / 2), "ci_high": np.quantile(boots, 1 - alpha / 2),
                    "mannwhitney_p": stats.mannwhitneyu(a, b).pvalue, "n_first": len(a), "n_second": len(b)},
                   rows, notes)


def _unit_stat(load, indicator, slice_, stat, p):
    series = _series(load(indicator, split=slice_), ["unit"], p["window"], p["confidence"])
    kept, _ = _eligible(series, stat, p["min_years"])
    return kept.set_index("unit")[stat]


def correlation(load, p):
    x = _unit_stat(load, p["indicator_x"], p.get("slice_x"), p["stat_x"], p)
    y = _unit_stat(load, p["indicator_y"], p.get("slice_y"), p["stat_y"], p)
    joined = pd.concat([x.rename("x"), y.rename("y")], axis=1, join="inner").dropna()
    n = len(joined)
    if n < 4:
        return _result({"n_units": n}, notes=["fewer than 4 units: no estimate"])
    fn = stats.spearmanr if p["method"] == "spearman" else stats.pearsonr
    r, pval = fn(joined["x"], joined["y"])
    pairs = joined.to_numpy()
    low, high = _bootstrap_ci(np.arange(n), lambda idx: fn(pairs[idx, 0], pairs[idx, 1])[0],
                              p["bootstrap"], p["seed"], p["confidence"])
    return _result({"r": r, "ci_low": low, "ci_high": high, "p": pval, "n_units": n},
                   joined.reset_index().rename(columns={"index": "unit"}))


def panel_fe_regression(load, p):
    y = load(p["indicator_y"], split=p.get("slice_y"))[["unit", "time", "value"]].rename(columns={"value": "y"})
    x = load(p["indicator_x"], split=p.get("slice_x"))[["unit", "time", "value"]].rename(columns={"value": "x"})
    df = y.merge(x, on=["unit", "time"]).dropna()
    df = df[df.groupby("unit")["unit"].transform("size") >= 2]
    if df["unit"].nunique() < 3 or df["time"].nunique() < 2:
        return _result({"n_units": df["unit"].nunique(), "n_obs": len(df)},
                       notes=["too few units or years for two-way fixed effects"])
    yd, xd = df["y"].astype(float).copy(), df["x"].astype(float).copy()
    for _ in range(200):  # alternating projections: remove unit and year means until stable
        prev = xd.copy()
        for key in ("unit", "time"):
            yd = yd - yd.groupby(df[key]).transform("mean")
            xd = xd - xd.groupby(df[key]).transform("mean")
        if np.allclose(prev, xd, atol=1e-10):
            break
    sxx = float((xd ** 2).sum())
    if sxx == 0:
        return _result({"n_units": df["unit"].nunique(), "n_obs": len(df)}, notes=["x has no within variation"])
    coef = float((xd * yd).sum() / sxx)
    resid = yd - coef * xd
    groups = df["unit"].to_numpy()
    meat = sum(float((xd[groups == g] * resid[groups == g]).sum()) ** 2 for g in np.unique(groups))
    g, n = len(np.unique(groups)), len(df)
    se = np.sqrt(meat * (g / (g - 1)) * ((n - 1) / (n - 2))) / sxx
    tcrit = float(stats.t.ppf(0.5 + p["confidence"] / 2, g - 1))
    return _result({"coef": coef, "ci_low": coef - tcrit * se, "ci_high": coef + tcrit * se,
                    "p": 2 * stats.t.sf(abs(coef / se), g - 1) if se > 0 else np.nan,
                    "n_units": g, "n_obs": n},
                   notes=["unit and year fixed effects; standard errors clustered by unit with correction "
                          "G/(G-1)·(N-1)/(N-2) (fixed effects not counted); t with G-1 degrees of freedom"])


# --- menu ----------------------------------------------------------------------

_CONF = Param("confidence", "float", False, 0.95)
_BOOT = Param("bootstrap", "int", False, 2000)
_SEED = Param("seed", "int", False, 42)
_WINDOW = Param("window", "int", False, 5, help="years in the recent window")
_MIN_YEARS = Param("min_years", "int", False, 10, help="minimum years for a slope")
_STAT = lambda name="stat": Param(name, "choice", True, None, STATS)

BLOCKS: dict[str, BlockSpec] = {b.name: b for b in (
    BlockSpec("series_trend", "linear trend of an indicator for every country (and split)",
              (Param("indicator", "indicator"), Param("split", "selector", False), _WINDOW, _MIN_YEARS, _CONF),
              ("n_series", "n_units", "mean_slope", "median_slope", "share_rising_ci", "share_falling_ci"),
              series_trend),
    BlockSpec("trajectory_class", "classify each series' recent trend as rising / stalled / reversed / saturated",
              (Param("indicator", "indicator"), Param("split", "selector", False), _WINDOW,
               Param("threshold", "float", help="minimum |slope| per year"),
               Param("saturation", "float", False, help="percent indicators only"), _MIN_YEARS, _CONF),
              ("n_series", "share_rising", "share_stalled", "share_reversed", "share_saturated"),
              trajectory_class),
    BlockSpec("paired_difference", "difference between two splits within the same country (first minus second)",
              (Param("indicator", "indicator"), Param("pair", "pair"), _STAT(), _WINDOW,
               Param("exclude_at_or_above", "float", False, help="percent indicators only"), _MIN_YEARS, _CONF,
               _BOOT, _SEED),
              ("mean", "median", "ci_low", "ci_high", "t_p", "wilcoxon_p", "cohens_d", "share_first_greater",
               "n_units"),
              paired_difference),
    BlockSpec("class_agreement", "how often two splits of the same country fall in different trajectory classes",
              (Param("indicator", "indicator"), Param("pair", "pair"), _WINDOW, Param("threshold", "float"),
               Param("saturation", "float", False, help="percent indicators only"), _MIN_YEARS, _CONF),
              ("disagreement_share", "ci_low", "ci_high", "n_units"),
              class_agreement),
    BlockSpec("group_comparison", "compare a per-country statistic between two groups of countries",
              (Param("indicator", "indicator"), Param("groups", "pair"), Param("slice", "slice", False), _STAT(),
               _WINDOW, _MIN_YEARS, _CONF, _BOOT, _SEED),
              ("mean_first", "mean_second", "difference", "ci_low", "ci_high", "mannwhitney_p", "n_first",
               "n_second"),
              group_comparison),
    BlockSpec("trajectory_group_comparison",
              "classify countries by the recent trajectory of one indicator, then compare a statistic of "
              "another indicator (or of a within-country split difference) between two classes",
              (Param("indicator", "indicator", help="classified by its total series"),
               Param("classes", "classes", help="two of rising, stalled, reversed, saturated, not_rising"),
               Param("threshold", "float"), Param("saturation", "float", False, help="percent indicators only"),
               Param("indicator_y", "indicator"), Param("slice_y", "slice", False), Param("pair_y", "pair", False),
               _STAT("stat_y"), _WINDOW, _MIN_YEARS, _CONF, _BOOT, _SEED),
              ("mean_first", "mean_second", "difference", "ci_low", "ci_high", "mannwhitney_p", "n_first",
               "n_second"),
              trajectory_group_comparison),
    BlockSpec("correlation", "correlation across countries between two per-country statistics",
              (Param("indicator_x", "indicator"), Param("indicator_y", "indicator"),
               Param("slice_x", "slice", False), Param("slice_y", "slice", False), _STAT("stat_x"), _STAT("stat_y"),
               Param("method", "choice", False, "spearman", ("spearman", "pearson")), _WINDOW, _MIN_YEARS, _CONF,
               _BOOT, _SEED),
              ("r", "ci_low", "ci_high", "p", "n_units"),
              correlation),
    BlockSpec("panel_fe_regression", "within-country association over time, country and year fixed effects",
              (Param("indicator_y", "indicator"), Param("indicator_x", "indicator"),
               Param("slice_y", "slice", False), Param("slice_x", "slice", False), _CONF),
              ("coef", "ci_low", "ci_high", "p", "n_units", "n_obs"),
              panel_fe_regression),
)}


def with_defaults(spec: BlockSpec, params: dict) -> dict:
    full = {p.name: p.default for p in spec.params if not p.required}
    full.update(params)
    return full


def describe_menu() -> str:
    """Prompt text listing every block, its parameters and outputs."""
    lines = []
    for b in BLOCKS.values():
        params = ", ".join(
            f"{p.name}{'' if p.required else '?'}:{p.kind}" + (f"[{'|'.join(p.choices)}]" if p.choices else "")
            for p in b.params)
        lines.append(f"- {b.name}: {b.summary}\n  params: {params}\n  outputs: {', '.join(b.outputs)}")
    return "\n".join(lines)

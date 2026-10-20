"""
Analysis blocks (tools/analysis_blocks.py) and the panel loader (tools/panel_data.py).

The blocks replace model-written analysis code. Expected values below were
computed by hand or taken from the fixed template validated on real WHO GHO
data on 2026-09-13 (paired urban-rural slope difference -0.152 for 194
countries, +0.301 for the 81 with neither area at or above 95%).
"""
import zipfile

import numpy as np
import pandas as pd
import pytest

from tools import analysis_blocks as ab
from tools.dataset_schema import DatasetSchema
from tools.panel_data import PanelDataError, detect_layout, load_indicator


def _loader(df):
    def load(indicator, split=None, attribute=None):
        part = df[df["indicator"] == indicator]
        if split:
            codes = split.partition(":")[2].split(",")
            part = part[part["split"].isin(codes)]
        else:
            part = part[part["split"] == "TOTL"]
        cols = ["unit", "time", "value"] + (["split"] if split else []) + (["attribute"] if attribute else [])
        return part[cols].reset_index(drop=True)
    return load


def _panel(slopes: dict[tuple[str, str], float], years=range(2000, 2012), noise=0.0, attribute=None):
    rng = np.random.default_rng(0)
    rows = []
    for (unit, split), slope in slopes.items():
        for t in years:
            rows.append({"indicator": "IND", "unit": unit, "split": split, "time": t,
                         "value": 50 + slope * (t - 2000) + rng.normal(0, noise),
                         "attribute": (attribute or {}).get(unit, "A")})
    return pd.DataFrame(rows)


def _run(name, df, **params):
    spec = ab.BLOCKS[name]
    return spec.run(_loader(df), ab.with_defaults(spec, params))


def test_trend_recovers_exact_slope_with_zero_width_ci_when_noiseless():
    slope, low, high = ab._trend(np.arange(10), 3 + 2 * np.arange(10), 0.95)
    assert slope == pytest.approx(2) and low == pytest.approx(2) and high == pytest.approx(2)


def test_paired_difference_is_first_minus_second_within_unit():
    df = _panel({("U1", "URB"): 1.0, ("U1", "RUR"): 0.5, ("U2", "URB"): 2.0, ("U2", "RUR"): 1.0,
                 ("U3", "URB"): 0.2, ("U3", "RUR"): 0.4, ("U4", "URB"): 1.0, ("U4", "RUR"): 1.0})
    out = _run("paired_difference", df, indicator="IND", pair="D:URB,RUR", stat="slope")["outputs"]
    assert out["mean"] == pytest.approx((0.5 + 1.0 - 0.2 + 0.0) / 4)
    assert out["n_units"] == 4
    assert out["share_first_greater"] == pytest.approx(0.5)


def test_exclusion_cap_drops_units_on_either_side_and_says_so():
    df = _panel({("U1", "URB"): 5.0, ("U1", "RUR"): 0.5, ("U2", "URB"): 1.0, ("U2", "RUR"): 0.2,
                 ("U3", "URB"): 1.2, ("U3", "RUR"): 0.1, ("U4", "URB"): 0.8, ("U4", "RUR"): 0.3})
    result = _run("paired_difference", df, indicator="IND", pair="D:URB,RUR", stat="slope", exclude_at_or_above=95)
    assert result["outputs"]["n_units"] == 3            # U1 urban reaches 100 in the recent window
    assert any("excluded" in n for n in result["notes"])


def test_too_few_units_gives_no_estimate_rather_than_a_number():
    df = _panel({("U1", "URB"): 1.0, ("U1", "RUR"): 0.5})
    result = _run("paired_difference", df, indicator="IND", pair="D:URB,RUR", stat="slope")
    assert "mean" not in result["outputs"] and "no estimate" in result["notes"][-1]


def test_trajectory_classes():
    df = _panel({("U1", "TOTL"): 2.0, ("U2", "TOTL"): 0.0, ("U3", "TOTL"): -2.0, ("U4", "TOTL"): 6.0}, noise=0.01)
    out = _run("trajectory_class", df, indicator="IND", threshold=0.25, saturation=95)["outputs"]
    assert out["share_rising"] == out["share_stalled"] == out["share_reversed"] == out["share_saturated"] == 0.25


def test_class_agreement_uses_wilson_interval():
    df = _panel({("U1", "URB"): 2.0, ("U1", "RUR"): 2.0, ("U2", "URB"): 2.0, ("U2", "RUR"): 0.0}, noise=0.01)
    out = _run("class_agreement", df, indicator="IND", pair="D:URB,RUR", threshold=0.25)["outputs"]
    assert out["disagreement_share"] == 0.5 and 0 < out["ci_low"] < 0.5 < out["ci_high"] < 1


def test_every_output_key_is_declared_in_the_spec():
    df = _panel({(f"U{i}", s): 0.5 + 0.1 * i + (0.3 if s == "URB" else 0) for i in range(8)
                 for s in ("URB", "RUR", "TOTL")}, noise=0.2,
                attribute={f"U{i}": "A" if i < 4 else "B" for i in range(8)})
    cases = {
        "series_trend": dict(indicator="IND"),
        "trajectory_class": dict(indicator="IND", threshold=0.25),
        "paired_difference": dict(indicator="IND", pair="D:URB,RUR", stat="slope", bootstrap=50),
        "class_agreement": dict(indicator="IND", pair="D:URB,RUR", threshold=0.25),
        "group_comparison": dict(indicator="IND", groups="G:A,B", stat="slope", bootstrap=50),
        "correlation": dict(indicator_x="IND", indicator_y="IND", stat_x="slope", stat_y="last_value", bootstrap=50),
        "trajectory_group_comparison": dict(indicator="IND", classes="rising,stalled", threshold=0.25,
                                            indicator_y="IND", pair_y="D:URB,RUR", stat_y="slope", bootstrap=50),
        "panel_fe_regression": dict(indicator_y="IND", indicator_x="IND"),
    }
    assert set(cases) == set(ab.BLOCKS)
    for name, params in cases.items():
        outputs = _run(name, df, **params)["outputs"]
        assert set(outputs) <= set(ab.BLOCKS[name].outputs), name


# --- loader -------------------------------------------------------------------------

def _gho_zip(tmp_path, rows):
    header = "IndicatorCode,SpatialDimension,SpatialDimensionValueCode,ParentLocationCode,TimeDim,DisaggregatingDimension1ValueCode,NumericValue"
    body = "\n".join(",".join(map(str, r)) for r in rows)
    path = tmp_path / "gho.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("data/IND.csv", header + "\n" + body + "\n")
    schema = DatasetSchema(
        url="x", files=["data/IND.csv"],
        columns=set(header.split(",")),
        values={"IndicatorCode": {"IND"}, "SpatialDimension": {"COUNTRY", "REGION"},
                "ParentLocationCode": {"AFR"},
                "DisaggregatingDimension1ValueCode": {"AREA_URB", "AREA_RUR", "AREA_TOTL"}},
        meanings={"IND": "Proportion (%)", "AFR": "Africa", "AREA_URB": "Urban", "AREA_RUR": "Rural",
                  "AREA_TOTL": "Total"})
    return detect_layout(schema, path)


def test_loader_uses_the_total_code_when_the_plan_does_not_split(tmp_path):
    rows = [("IND", "COUNTRY", "KEN", "AFR", 2000, code, v) for code, v in
            (("AREA_URB", 60), ("AREA_RUR", 10), ("AREA_TOTL", 25))]
    rows.append(("IND", "REGION", "AFR", "", 2000, "AREA_TOTL", 30))
    layout = _gho_zip(tmp_path, rows)
    df = load_indicator(layout, "IND")
    assert df.to_dict("records") == [{"unit": "KEN", "time": 2000, "value": 25.0}]
    split = load_indicator(layout, "IND", split="DisaggregatingDimension1ValueCode:AREA_URB,AREA_RUR")
    assert sorted(split["split"]) == ["AREA_RUR", "AREA_URB"]


def test_loader_refuses_to_guess_when_there_is_no_total(tmp_path):
    rows = [("IND", "COUNTRY", "KEN", "AFR", 2000, code, v) for code, v in (("AREA_URB", 60), ("AREA_RUR", 10))]
    layout = _gho_zip(tmp_path, rows)
    with pytest.raises(PanelDataError, match="does not choose"):
        load_indicator(layout, "IND")

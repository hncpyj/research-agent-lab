"""
A second dataset shape: one row per country-year, one column per indicator.

M7 asks for a validation run on a dataset that was not used to tune anything.
Until 2026-09-20 the data layer only read WHO GHO's shape (an indicator-code
column plus a SpatialDimType marker), so any other public panel was blocked
at the audit — the pipeline was fitted to one file.
"""
import pytest

from agents.data_audit import DataAuditError, build_audit
from tools.dataset_schema import DatasetSchema
from tools.panel_data import PanelDataError, country_rows, detect_layout, load_indicator

CSV = """country,iso_code,year,renewables_share_energy,energy_per_capita
France,FRA,2000,6.2,45000
France,FRA,2001,6.9,45500
Kenya,KEN,2000,70.1,3000
Kenya,KEN,2001,71.4,3100
World,OWID_WRL,2000,13.0,20000
World,OWID_WRL,2001,13.2,20200
Africa (Ember),,2000,11.0,2500
"""


@pytest.fixture
def dataset(tmp_path):
    path = tmp_path / "owid-energy.csv"
    path.write_text(CSV, encoding="utf-8")
    schema = DatasetSchema(url="https://example.org/owid-energy.csv", files=["owid-energy.csv"],
                           columns={"country", "iso_code", "year",
                                    "renewables_share_energy", "energy_per_capita"},
                           values={"country": {"France", "Kenya", "World", "Africa (Ember)"}})
    return schema, path


def test_the_indicators_are_the_numeric_columns(dataset):
    schema, path = dataset
    layout = detect_layout(schema, path)
    assert layout.kind == "indicator_columns"
    assert layout.indicators == ["energy_per_capita", "renewables_share_energy"]
    assert layout.unit_column == "iso_code" and layout.time_column == "year"
    assert "three-letter country code" in layout.unit_rule


def test_aggregates_are_not_counted_as_countries(dataset):
    schema, path = dataset
    layout = detect_layout(schema, path)
    tidy = load_indicator(layout, "renewables_share_energy")
    assert sorted(tidy["unit"].unique()) == ["FRA", "KEN"]
    assert len(tidy) == 4
    assert tidy.iloc[0]["value"] == pytest.approx(6.2)


def test_asking_for_a_split_this_data_does_not_have_fails_loudly(dataset):
    schema, path = dataset
    layout = detect_layout(schema, path)
    with pytest.raises(PanelDataError, match="no disaggregation"):
        load_indicator(layout, "renewables_share_energy", split="Dim1:URB,RUR")
    with pytest.raises(PanelDataError, match="not a column"):
        load_indicator(layout, "policy_stringency")


def test_the_audit_memo_describes_both_indicators(dataset):
    schema, path = dataset
    audit = build_audit(schema, path, {"text": "Does renewable share rise with energy use?"})
    codes = {i["code"]: i for i in audit["indicators"]}
    assert set(codes) == {"renewables_share_energy", "energy_per_capita"}
    assert codes["renewables_share_energy"]["n_countries"] == 2
    assert codes["renewables_share_energy"]["years"] == [2000, 2001]
    assert audit["units"]["rule"].startswith("rows whose iso_code")
    assert any("aggregates are left out" in l for l in audit["limits"])


def test_a_file_that_is_not_a_panel_is_refused(tmp_path):
    path = tmp_path / "notes.csv"
    path.write_text("name,comment\nx,hello\n", encoding="utf-8")
    schema = DatasetSchema(url="u", files=["notes.csv"], columns={"name", "comment"},
                           values={"name": {"x"}, "comment": {"hello"}})
    with pytest.raises(DataAuditError, match="not a panel of indicators over time"):
        build_audit(schema, path, {"text": "?"})


def test_a_panel_with_no_country_codes_is_refused(tmp_path):
    path = tmp_path / "regions.csv"
    path.write_text("code,year,value\nEUROPE,2000,1.0\n", encoding="utf-8")
    schema = DatasetSchema(url="u", files=["regions.csv"], columns={"code", "year", "value"},
                           values={"code": {"EUROPE"}})
    with pytest.raises(DataAuditError, match="no three-letter country codes"):
        build_audit(schema, path, {"text": "?"})


def test_country_rows_still_uses_the_marker_column_when_there_is_one():
    import pandas as pd

    from tools.panel_data import PanelLayout
    layout = PanelLayout(path="x", indicator_column="IndicatorCode", unit_type_column="SpatialDimType",
                         unit_type_value="COUNTRY", unit_column="SpatialDimValueCode",
                         time_column="TimeDim", value_column="NumericValue")
    raw = pd.DataFrame({"SpatialDimType": ["COUNTRY", "REGION"], "SpatialDimValueCode": ["FRA", "EUR"]})
    assert list(country_rows(layout, raw)["SpatialDimValueCode"]) == ["FRA"]


def test_a_wide_dataset_is_cut_to_the_indicators_the_question_is_about(tmp_path):
    """127 indicators do not fit in one prompt; what was left out is stated, not dropped."""
    columns = ["country", "iso_code", "year", "renewables_share_elec", "fossil_share_elec"]
    filler = [f"other_metric_{i}" for i in range(20)]
    rows = [",".join(columns + filler)]
    for year in (2000, 2001):
        measurements = ",".join(["1.0"] * (2 + len(filler)))
        rows.append(f"France,FRA,{year},{measurements}")
    path = tmp_path / "wide.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    schema = DatasetSchema(url="u", files=["wide.csv"], columns=set(columns + filler),
                           values={"country": {"France"}})
    audit = build_audit(schema, path, {"text": "Does renewable electricity displace fossil electricity?"},
                        max_indicators=3)

    listed = [i["code"] for i in audit["indicators"]]
    assert "renewables_share_elec" in listed and "fossil_share_elec" in listed
    assert len(listed) == 3 and audit["indicators_omitted"] == 19
    assert any("cannot be written from this memo" in l for l in audit["limits"])


def test_rows_with_no_country_code_are_never_treated_as_one_country(tmp_path):
    """
    pandas 2.x renders a missing code as the string "nan", which is three
    letters; every aggregate row then became a single unit called "nan".
    The runner runs on pandas 2.3, the tests on 3.0, so this is pinned here
    against both spellings of "missing".
    """
    import numpy as np
    import pandas as pd

    from tools.panel_data import PanelLayout, _is_country_code

    layout = PanelLayout(path="x", indicator_column="", unit_type_column="", unit_type_value="",
                         unit_column="iso_code", time_column="year", value_column="",
                         kind="indicator_columns", indicators=["v"])
    raw = pd.DataFrame({
        "country": ["France", "World", "ASEAN (Ember)", "Kenya"],
        "iso_code": ["FRA", np.nan, None, "KEN"],
        "year": [2000, 2000, 2000, 2000],
        "v": [1.0, 2.0, 3.0, 4.0],
    })
    assert list(_is_country_code(raw["iso_code"])) == [True, False, False, True]
    assert list(country_rows(layout, raw)["country"]) == ["France", "Kenya"]

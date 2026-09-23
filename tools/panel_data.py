"""
Layout detection and loading for long-format indicator panels (one row per
indicator × spatial unit × year × disaggregation, e.g. WHO GHO bulk files).

This file is copied into each session's experiment folder and imported by the
generated run script, so it depends only on the standard library, numpy and
pandas — no project imports.

What it refuses to guess:
- An indicator split by a dimension the plan did not choose (e.g. urban/rural)
  is reduced to that dimension's total code when the data has one; otherwise
  loading fails with the codes it found. Silently averaging or picking the
  first code would change what is being measured.
- Duplicate (unit, year, split) rows after filtering fail loading.
"""

from __future__ import annotations

import io
import os
import re
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

TOTAL_MEANINGS = {"total", "both sexes", "both", "all", "all ages"}


class PanelDataError(Exception):
    """The data does not have the structure the plan relies on."""


@dataclass
class PanelLayout:
    path: str
    indicator_column: str
    unit_type_column: str
    unit_type_value: str
    unit_column: str
    time_column: str
    value_column: str
    dimension_columns: list[str] = field(default_factory=list)
    attribute_columns: list[str] = field(default_factory=list)
    total_codes: list[str] = field(default_factory=list)
    members: dict[str, str] = field(default_factory=dict)  # indicator code -> file inside the archive
    # "indicator_rows": one row per indicator × unit × year, with an indicator-code
    # column (WHO GHO bulk files). "indicator_columns": one row per unit × year
    # with one column per indicator (Our World in Data style). Detection is not
    # a guess in either case: see detect_layout.
    kind: str = "indicator_rows"
    indicators: list[str] = field(default_factory=list)   # indicator_columns only
    unit_rule: str = ""                                   # how country rows were identified

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PanelLayout":
        return cls(**data)


def detect_layout(schema, path: Path | str) -> PanelLayout:
    """Build the layout from a tools.dataset_schema.DatasetSchema. Raises PanelDataError."""
    cols, values, meanings = schema.columns, schema.values, schema.meanings

    indicator = next((c for c in sorted(values) if "indicator" in c.lower()), None)
    if indicator is None:
        # Second family: the indicators are the columns (one row per unit-year).
        return _detect_indicator_columns(schema, path)
    unit_type = next((c for c in sorted(values) if "COUNTRY" in values[c]), None)
    if unit_type is None or f"{unit_type}ValueCode" not in cols:
        raise PanelDataError("no column marking country-level rows with a matching ...ValueCode column")
    time = "TimeDim" if "TimeDim" in cols else next((c for c in sorted(cols) if c.lower() in ("year", "time")), None)
    value = "NumericValue" if "NumericValue" in cols else ("Value" if "Value" in cols else None)
    if time is None or value is None:
        raise PanelDataError("no year column or numeric value column")

    taken = {indicator, unit_type, f"{unit_type}ValueCode"}
    dims = sorted(c for c in values if c not in taken and "dimension" in c.lower()
                  and c.endswith("ValueCode") and any(v in meanings for v in values[c]))
    attrs = sorted(c for c in values if c not in taken and c not in dims and c.endswith("Code")
                   and any(v in meanings for v in values[c]))
    totals = sorted(v for c in dims for v in values[c] if meanings.get(v, "").strip().lower() in TOTAL_MEANINGS)
    members = {Path(f).stem: f for f in schema.files if Path(f).stem in values[indicator]}

    return PanelLayout(path=str(path), indicator_column=indicator, unit_type_column=unit_type,
                       unit_type_value="COUNTRY", unit_column=f"{unit_type}ValueCode", time_column=time,
                       value_column=value, dimension_columns=dims, attribute_columns=attrs,
                       total_codes=totals, members=members)


_UNIT_COLUMN_NAMES = ("iso_code", "iso3", "iso3_code", "country_code", "countrycode",
                      "country code", "code", "geo", "entity_code", "ref_area")
_TIME_COLUMN_NAMES = ("year", "time", "period", "time_period", "timeperiod", "date")
_COUNTRY_CODE = re.compile(r"[A-Za-z]{3}$")


def _detect_indicator_columns(schema, path: Path | str) -> PanelLayout:
    """
    One row per unit and year, one column per indicator. Which columns are
    indicators is read from the file itself (numeric dtype), and country rows
    are the ones carrying a three-letter country code — aggregates such as
    "World" or "Africa (Ember)" do not have one, and are not silently mixed
    into country-level statistics.
    """
    lower = {c.lower(): c for c in schema.columns}
    unit = next((lower[n] for n in _UNIT_COLUMN_NAMES if n in lower), None)
    time = next((lower[n] for n in _TIME_COLUMN_NAMES if n in lower), None)
    if unit is None or time is None:
        raise PanelDataError("no indicator-code column, and no country-code and year columns either: "
                             "this is not a panel of indicators over time")

    sample = _sample_frame(path)
    for column in (unit, time):
        if column not in sample.columns:
            raise PanelDataError(f"column {column} is not in the data file")
    if not _is_country_code(sample[unit]).any():
        raise PanelDataError(f"column {unit} holds no three-letter country codes, so country rows "
                             "cannot be told apart from aggregates")
    numeric = [c for c in sample.select_dtypes(include="number").columns
               if c not in (unit, time) and sample[c].notna().any()]
    if not numeric:
        raise PanelDataError("no numeric indicator column in the data file")

    return PanelLayout(path=str(path), kind="indicator_columns", indicator_column="",
                       unit_type_column="", unit_type_value="", unit_column=unit,
                       time_column=time, value_column="", indicators=sorted(numeric),
                       unit_rule=f"rows whose {unit} is a three-letter country code")


def _sample_frame(path: Path | str, rows: int = 20000) -> pd.DataFrame:
    """The first rows of the data file, used to see which columns are numeric."""
    path = Path(path)
    if not zipfile.is_zipfile(path):
        return pd.read_csv(path, nrows=rows, low_memory=False)
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist()
                 if n.lower().endswith(".csv") and not n.endswith("/") and _safe_member(n)]
        if not names:
            raise PanelDataError(f"no CSV inside {path.name}")
        return pd.read_csv(io.BytesIO(_read_member(zf, names[0])), nrows=rows, low_memory=False)


def _is_country_code(column: pd.Series) -> pd.Series:
    """
    Which entries are three-letter country codes. Missing values are emptied
    first: pandas 2.x turns a missing code into the string "nan" on astype(str)
    (pandas 3.x keeps it missing), and "nan" is three letters — every World and
    region row then passed as one country called "nan". The runner runs on
    pandas 2.3 and the test suite on 3.0, so this only showed up in a real run.
    """
    text = column.where(column.notna(), "").astype(str).str.strip()
    return text.str.fullmatch(_COUNTRY_CODE).fillna(False)


def country_rows(layout: PanelLayout, raw: pd.DataFrame) -> pd.DataFrame:
    """Only the country-level rows, by whichever rule this layout was built on."""
    if layout.unit_type_column:
        return raw[raw[layout.unit_type_column] == layout.unit_type_value]
    return raw[_is_country_code(raw[layout.unit_column])]


def indicator_codes(layout: PanelLayout, schema=None) -> list[str]:
    """Every indicator this layout offers."""
    if layout.kind == "indicator_columns":
        return list(layout.indicators)
    if schema is None:
        return []
    return sorted(schema.values.get(layout.indicator_column, set()))


def parse_selector(text: str) -> tuple[str, list[str]]:
    """'Column:CODE_A,CODE_B' -> ('Column', ['CODE_A', 'CODE_B'])."""
    column, _, codes = text.partition(":")
    return column.strip(), [c.strip() for c in codes.split(",") if c.strip()]


def _safe_member(name: str) -> bool:
    """An archive member may not name a path outside the folder it is read into."""
    return not name.startswith(("/", "\\")) and ".." not in name.replace("\\", "/").split("/")


def _read_member(zf: zipfile.ZipFile, name: str, max_expansion: int = 100) -> bytes:
    """Read one member, refusing an archive that expands far beyond its stored size."""
    limit = int(os.environ.get("DATASET_MAX_MB", "200")) * 1024 * 1024
    info = zf.getinfo(name)
    if info.file_size > limit or (info.compress_size
                                  and info.file_size / info.compress_size > max_expansion):
        raise PanelDataError(f"{name} expands to {info.file_size / 1e6:.0f} MB — refused")
    with zf.open(name) as fh:
        data = fh.read(limit + 1)
    if len(data) > limit:
        raise PanelDataError(f"{name} is larger than DATASET_MAX_MB")
    return data


def _read_raw(layout: PanelLayout, indicator: str) -> pd.DataFrame:
    path = Path(layout.path)
    needed = indicator if layout.kind == "indicator_columns" else layout.indicator_column
    if not zipfile.is_zipfile(path):
        return pd.read_csv(path, low_memory=False)
    with zipfile.ZipFile(path) as zf:
        names = [layout.members[indicator]] if indicator in layout.members else [
            n for n in zf.namelist()
            if n.lower().endswith(".csv") and not n.endswith("/") and _safe_member(n)]
        frames = []
        for name in names:
            frame = pd.read_csv(io.BytesIO(_read_member(zf, name)), low_memory=False)
            if needed in frame.columns:
                frames.append(frame)
    if not frames:
        raise PanelDataError(f"no table in {path.name} has column {needed}")
    return pd.concat(frames, ignore_index=True)


def _load_indicator_column(layout: PanelLayout, indicator: str, split, attribute) -> pd.DataFrame:
    """One indicator from a unit-year table whose columns are the indicators."""
    if split or attribute:
        raise PanelDataError(f"{Path(layout.path).name} has no disaggregation columns, so "
                             f"{split or attribute} cannot be used")
    if indicator not in layout.indicators:
        raise PanelDataError(f"{indicator} is not a column of this dataset")
    raw = country_rows(layout, _read_raw(layout, indicator))
    if raw.empty:
        raise PanelDataError(f"indicator {indicator} has no country-level rows")

    tidy = pd.DataFrame({
        "unit": raw[layout.unit_column].astype(str).str.strip(),
        "time": pd.to_numeric(raw[layout.time_column], errors="coerce"),
        "value": pd.to_numeric(raw[indicator], errors="coerce"),
    }).dropna(subset=["time", "value"])
    tidy["time"] = tidy["time"].astype(int)
    dupes = tidy.duplicated(["unit", "time"]).sum()
    if dupes:
        raise PanelDataError(f"{indicator}: {dupes} duplicate rows per ['unit', 'time']")
    return tidy.sort_values(["unit", "time"]).reset_index(drop=True)


def load_indicator(layout: PanelLayout, indicator: str, split: str | None = None,
                   attribute: str | None = None) -> pd.DataFrame:
    """
    Tidy rows for one indicator at country level: unit, time, value, plus a
    `split` column (the chosen dimension's code) and an `attribute` column
    (a unit-level grouping such as the WHO region) when requested.
    """
    if layout.kind == "indicator_columns":
        return _load_indicator_column(layout, indicator, split, attribute)

    raw = _read_raw(layout, indicator)
    raw = country_rows(layout, raw[raw[layout.indicator_column] == indicator])
    if raw.empty:
        raise PanelDataError(f"indicator {indicator} has no country-level rows")

    split_col, split_codes = parse_selector(split) if split else (None, [])
    if split_col is not None:
        if split_col not in raw.columns:
            raise PanelDataError(f"column {split_col} not in the data for {indicator}")
        raw = raw[raw[split_col].isin(split_codes)]
        missing = set(split_codes) - set(raw[split_col].unique())
        if missing:
            raise PanelDataError(f"{indicator} has no rows for {sorted(missing)} in {split_col}")

    for col in layout.dimension_columns:
        if col == split_col or col not in raw.columns:
            continue
        present = sorted(raw[col].dropna().unique())
        if len(present) <= 1:
            continue
        totals = [c for c in present if c in layout.total_codes]
        if len(totals) != 1:
            raise PanelDataError(
                f"{indicator} is split by {col} ({', '.join(present[:6])}) and the plan does not "
                "choose which to use, and the data has no single total code")
        raw = raw[raw[col] == totals[0]]

    tidy = pd.DataFrame({
        "unit": raw[layout.unit_column].astype(str),
        "time": pd.to_numeric(raw[layout.time_column], errors="coerce"),
        "value": pd.to_numeric(raw[layout.value_column], errors="coerce"),
    })
    if split_col is not None:
        tidy["split"] = raw[split_col].astype(str)
    if attribute:
        attr_col, attr_codes = parse_selector(attribute)
        if attr_col not in raw.columns:
            raise PanelDataError(f"column {attr_col} not in the data for {indicator}")
        tidy["attribute"] = raw[attr_col].astype(str)
        tidy = tidy[tidy["attribute"].isin(attr_codes)]
    tidy = tidy.dropna(subset=["time", "value"])
    tidy["time"] = tidy["time"].astype(int)

    keys = ["unit", "time"] + (["split"] if split_col is not None else [])
    dupes = tidy.duplicated(keys).sum()
    if dupes:
        raise PanelDataError(f"{indicator}: {dupes} duplicate rows per {keys} after filtering")
    return tidy.sort_values(keys).reset_index(drop=True)

"""
Read what a session's declared dataset actually contains, so research
questions can be checked against real columns instead of a model's guess.

A 2026-09-13 run labeled every research question "Feasibility: Yes" —
including ones needing fuel-stacking or intervention variables the declared
WHO GHO download does not contain. This module finds dataset URLs in the
brief, downloads the file once (paced and block-aware like every external
request), and extracts:
- every column header in each CSV/TSV (also inside .zip archives)
- the distinct values of low-cardinality text columns, because long-format
  datasets such as WHO GHO put the actual variables in an indicator-code
  column rather than in the headers

Hosting limits checked 2026-09-13: WHO's bulk files are on Azure Blob
Storage (20,000 requests/s per account; throttles with 429 or 503
ServerBusy) — https://learn.microsoft.com/en-us/azure/storage/blobs/scalability-targets
"""

from __future__ import annotations

import csv
import io
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import config
from tools.rate_limit import SourceBlocked, get_limiter, is_rate_limit_status
from tools.url_safety import UnsafeURL, check_url, opener, read_zip_member, safe_members

_URL_RE = re.compile(r"https?://[^\s<>\"')]+?\.(?:zip|csv|tsv)(?:\?[^\s<>\"')]*)?", re.IGNORECASE)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_MAX_ROWS = 200_000
_MAX_DISTINCT = 200


class DatasetUnavailable(Exception):
    """The declared dataset could not be downloaded or parsed."""


@dataclass
class DatasetSchema:
    url: str
    files: list[str] = field(default_factory=list)
    columns: set[str] = field(default_factory=set)
    values: dict[str, set[str]] = field(default_factory=dict)
    # code -> human-readable meaning, from the dataset's own code tables
    # (tables with Code and Title columns, e.g. WHO GHO's codes/*.csv)
    meanings: dict[str, str] = field(default_factory=dict)

    def used_codes(self) -> dict[str, str]:
        """Meanings for codes that actually occur in the data (not every code the tables define)."""
        present = set()
        for vals in self.values.values():
            present.update(vals)
        return {c: m for c, m in self.meanings.items() if c in present}

    def vocabulary(self) -> set[str]:
        """Lower-cased names (columns, values, code meanings) a question may rely on."""
        vocab = {c.lower() for c in self.columns}
        for vals in self.values.values():
            vocab.update(v.lower() for v in vals)
        vocab.update(m.lower() for m in self.used_codes().values())
        return vocab

    def meaning_of(self, name: str) -> str:
        """What a column, code, or code title refers to; the name itself if nothing better."""
        key = name.strip()
        if key in self.meanings:
            return self.meanings[key]
        lowered = key.lower()
        for code, meaning in self.used_codes().items():
            if code.lower() == lowered or meaning.lower() == lowered:
                return meaning
        return key

    def describe(self, max_values: int = 40) -> str:
        """
        Prompt text. Codes are listed with their meanings in full — an earlier
        version listed raw values alphabetically and cut each list at 80, which
        hid what indicator codes meant, and a model then mapped "fuel stacking
        rates" to a polluting-fuel indicator by guessing from the code name.
        """
        used = self.used_codes()
        lines = [f"Source: {self.url}", f"Columns: {', '.join(sorted(self.columns))}"]
        for col in sorted(self.values):
            vals = self.values[col]
            codes = sorted(v for v in vals if v in used)
            if codes:
                if len(codes) <= max_values:
                    lines.append(f"Codes in {col}:")
                    lines += [f"  {c}: {used[c]}" for c in codes]
                else:  # e.g. ~200 country codes: the fact matters, the full list does not
                    examples = ", ".join(f"{c}: {used[c]}" for c in codes[:5])
                    lines.append(f"Codes in {col}: {len(codes)} codes, e.g. {examples}")
            others = sorted(v for v in vals if v not in used)
            if not others or all(_DATE_RE.match(v) for v in others):
                continue  # timestamps: header is enough
            shown = ", ".join(others[:max_values]) + (f" … ({len(others)} values)" if len(others) > max_values else "")
            lines.append(f"Values of {col}: {shown}")
        return "\n".join(lines)


def find_dataset_urls(*texts: str) -> list[str]:
    urls: list[str] = []
    for text in texts:
        for url in _URL_RE.findall(text or ""):
            if url not in urls:
                urls.append(url)
    return urls


def load_schema(url: str, cache_dir: Path | None = None) -> DatasetSchema:
    """Download (once) and parse. Raises DatasetUnavailable or SourceBlocked."""
    path = _download(url, cache_dir if cache_dir is not None else config.DATASETS_DIR)
    schema = DatasetSchema(url=url)
    try:
        if zipfile.is_zipfile(path):
            limit_bytes = config.DATASET_MAX_MB * 1024 * 1024
            with zipfile.ZipFile(path) as zf:
                for name in safe_members(zf):
                    raw = io.BytesIO(read_zip_member(zf, name, limit_bytes))
                    _parse_table(io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace"),
                                 name, schema)
        elif path.suffix.lower() in (".csv", ".tsv"):
            with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
                _parse_table(fh, path.name, schema)
    except (zipfile.BadZipFile, csv.Error, UnsafeURL) as exc:
        raise DatasetUnavailable(f"could not parse {url}: {exc}") from exc
    if not schema.columns:
        raise DatasetUnavailable(f"no CSV/TSV tables found in {url}")
    return schema


def cached_path(url: str, cache_dir: Path | None = None) -> Path:
    """Where a declared dataset is stored locally once downloaded."""
    cache_dir = cache_dir if cache_dir is not None else config.DATASETS_DIR
    parsed = urllib.parse.urlparse(url)
    name = Path(parsed.path).name or "dataset"
    return cache_dir / f"{parsed.netloc}_{name}"


def _fetch(req: urllib.request.Request, timeout: int):
    """Single place the network is touched, so redirects stay checked."""
    return opener().open(req, timeout=timeout)


def _download(url: str, cache_dir: Path) -> Path:
    parsed = urllib.parse.urlparse(url)
    name = Path(parsed.path).name or "dataset"
    path = cached_path(url, cache_dir)
    if path.exists() and path.stat().st_size > 0:
        return path

    try:
        check_url(url)                  # a brief is not always written by the person running it
    except UnsafeURL as exc:
        raise DatasetUnavailable(str(exc)) from exc
    source = f"host:{parsed.netloc}"
    limiter = get_limiter()
    limiter.acquire(source)
    limit_bytes = config.DATASET_MAX_MB * 1024 * 1024
    req = urllib.request.Request(url, headers={"User-Agent": "research-agent-lab/1.0"})
    try:
        with _fetch(req, 120) as resp:
            declared = int(resp.headers.get("Content-Length") or 0)
            if declared > limit_bytes:
                raise DatasetUnavailable(
                    f"{url} is {declared / 1e6:.0f} MB, above DATASET_MAX_MB={config.DATASET_MAX_MB}"
                )
            data = resp.read(limit_bytes + 1)
    except urllib.error.HTTPError as exc:
        if is_rate_limit_status(source, exc.code):
            until = limiter.block(source, f"HTTP {exc.code} downloading {name}")
            raise SourceBlocked(source, until, f"HTTP {exc.code}") from exc
        raise DatasetUnavailable(f"HTTP {exc.code} downloading {url}") from exc
    except urllib.error.URLError as exc:
        raise DatasetUnavailable(f"could not reach {url}: {exc.reason}") from exc
    if len(data) > limit_bytes:
        raise DatasetUnavailable(f"{url} exceeds DATASET_MAX_MB={config.DATASET_MAX_MB}")

    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


def _parse_table(fh, name: str, schema: DatasetSchema) -> None:
    sample = fh.read(8192)  # sniff the delimiter, then parse sample + rest of stream
    delimiter = "\t" if name.lower().endswith(".tsv") or sample.count("\t") > sample.count(",") else ","
    reader = csv.reader(_chain(sample, fh), delimiter=delimiter)

    header = next(reader, None)
    if not header:
        return
    header = [h.strip() for h in header]
    schema.files.append(name)

    lowered = [h.lower() for h in header]
    if "code" in lowered and "title" in lowered:
        # A code table: it defines what codes mean, it is not data itself.
        ci, ti = lowered.index("code"), lowered.index("title")
        for row in reader:
            if len(row) > max(ci, ti) and row[ci].strip() and row[ti].strip():
                schema.meanings[row[ci].strip()] = row[ti].strip()
        return

    schema.columns.update(h for h in header if h)

    distinct: dict[int, set[str]] = {i: set() for i in range(len(header))}
    numeric: dict[int, int] = {i: 0 for i in range(len(header))}
    for n, row in enumerate(reader):
        if n >= _MAX_ROWS:
            break
        for i, cell in enumerate(row[: len(header)]):
            if i not in distinct:
                continue
            cell = cell.strip()
            if not cell:
                continue
            if _is_number(cell):
                numeric[i] += 1
                continue
            distinct[i].add(cell)
            if len(distinct[i]) > _MAX_DISTINCT:
                del distinct[i]  # high-cardinality (names, free text) — headers only

    for i, vals in distinct.items():
        if vals and numeric[i] <= len(vals):
            schema.values.setdefault(header[i], set()).update(vals)


def _chain(first: str, rest):
    """Yield lines from an already-read prefix followed by the remaining stream."""
    buf = ""
    for chunk in _prepend(first, iter(lambda: rest.read(65536), "")):
        buf += chunk
        *lines, buf = buf.split("\n")
        for line in lines:
            yield line + "\n"
    if buf:
        yield buf


def _prepend(first: str, chunks):
    yield first
    yield from chunks

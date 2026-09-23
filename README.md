# AI Research Agent

Vague research topic → papers → gap analysis → hypotheses → runnable experiment code → results → peer-review-style quality check → report (MD/LaTeX/PDF).

Two ways to use it: a **Web UI** (primary, recommended) or the original **CLI**. Both drive the same 8-phase pipeline and share the same SQLite session store, so a session started in one can be resumed from the other.

---

## Quick Start

### 1. Python environment

```bash
python -m pip install -r requirements.txt
```

Tested on Python 3.14 (Windows/macOS/Linux). `ChromaDB` is commented out of `requirements.txt` by default — it's only used by the CLI's embedding-based similarity search (never by the Web UI, see [Local model backends](#local-model-backends) below) and has no wheel for 3.14 at the time of writing. If you're running the CLI path, `pip install chromadb` separately on Python ≤3.12.

### 2. Local model backend (optional but recommended)

The system prefers **Ollama** for local inference — no GGUF file management needed:

```bash
# https://ollama.com
ollama pull llama3.1:8b        # or any model; OLLAMA_MODEL does prefix-matching
ollama pull nomic-embed-text   # paper relevance ranking in Phase 1
```

If Ollama isn't running, `OllamaModel.load()` auto-starts `ollama serve`. If Ollama isn't installed at all, the system falls back to `llama-cpp-python` + a local GGUF file (see `.env.example` for `LOCAL_MODEL_PATH` / `EMBED_MODEL_PATH`), and if that's also unavailable it runs in **API-only mode** using Claude for everything.

### 3. Set your Anthropic API key

Copy `.env.example` to `.env` and fill in `ANTHROPIC_API_KEY`, or export it directly:

```bash
export ANTHROPIC_API_KEY=sk-ant-...        # macOS / Linux
$env:ANTHROPIC_API_KEY = "sk-ant-..."      # PowerShell
```

The Web UI also has an **API on/off toggle** in the top nav bar — turn it off to force every phase through the local model and spend $0, without touching `.env`.

### 4. Run — Web UI (recommended)

```bash
python run_ui.py
# opens http://localhost:8000
```

Create a session from the browser (topic + optional background/goals/constraints), pick a research question when prompted, and watch the pipeline stream through the browser via WebSocket.

### 5. Run — CLI (alternative)

```bash
python main.py                                          # interactive prompt
python main.py --topic "transformer attention efficiency"
python main.py --session <session_id>                    # resume
python main.py --list-sessions                           # show saved sessions
python main.py --skip-local                               # API-only, skip local model
python main.py --session <id> --experiment                # re-run Phase 5 only
python main.py --session <id> --run-experiment            # re-run Phase 6 only
```

---

## Architecture

```
main.py / run_ui.py
  └─ Orchestrator (CLI)  /  SessionRunner (Web UI)
       ├─ Phase 1  PaperCollectionAgent    [LOCAL]      multi-source search + canon-seed + embed + rank
       ├─ Phase 2  LiteratureReviewAgent   [LOCAL]      structured extraction + comparison table
       ├─ Phase 3  GapAnalysisAgent        [API]        gap report + validation + research question candidates (user picks one)
       ├─ Phase 4  HypothesisAgent         [API+LOCAL]  brainstorm + novelty check + refine
       ├─ Phase 5  ExperimentAgent         [API]        generate a runnable, domain-specific experiment codebase
       │             ↳ pre-execution domain-alignment gate (fast, no eval data needed)
       ├─ Phase 6  ExperimentRunnerAgent   [subprocess+API]  pip install → pretrain → train → evaluate, with LLM auto-fix on failure
       ├─ Phase 7  QualityReviewAgent      [API]        AI-judge peer review + rule-based checks (never blocks the pipeline)
       └─ Phase 8  ReportAgent             [API, on-demand]  one LLM call → structured JSON → rendered to Markdown/LaTeX/PDF
```

Every phase (1–6) is wrapped by `SelfBugFixAgent` (`agents/self_bugfix_agent.py`), which retries on transient errors, asks the LLM to repair malformed JSON, or injects a hint on `KeyError`/`AttributeError`/`TypeError` before retrying.

Session status is persisted in SQLite after each phase (`started → papers_collected → review_done → question_selected → hypotheses_generated → code_generated → experiment_run`), so both the CLI and the Web UI can resume a session and skip already-completed phases.

### Local model backends

| Priority | Backend | Notes |
|---|---|---|
| 1 | **Ollama** (`models/ollama_model.py`) | HTTP client to a local Ollama server; auto-starts `ollama serve`; resolves `OLLAMA_MODEL` by exact/prefix match |
| 2 | **llama-cpp-python GGUF** (`models/local_model.py`) | Qwen2.5-14B-Instruct Q4 + nomic-embed-text; requires downloaded `.gguf` files |
| 3 | **API-only** | Claude handles every task; no local model registered |

The chosen local model is injected into `APIModel` as its offline fallback (`api_model.set_local_model(...)`), and is also used directly for LOCAL-routed tasks (keyword extraction, paper summarisation, embeddings) per `router.py`.

**Web UI note:** the UI never loads `ChromaDB` (`ui/runner.py`'s `_DummyVectorDB`) because ChromaDB is incompatible with Python 3.14 at the time of writing. Papers and hypotheses are read from SQLite only; embedding-based similarity search is inert in the Web UI path (zero vectors), same as `--skip-local` in the CLI.

### Web UI (`ui/`)

- `ui/app.py` — FastAPI routes + `/ws/{session_id}` WebSocket
- `ui/runner.py` — `SessionRunner` runs the pipeline in a background thread; `QueueConsole` monkey-patches each agent module's `console` object so `rich` output becomes structured JSON events on the queue
- `ui/report_renderer.py` — turns the Phase 8 JSON report into Markdown / LaTeX / PDF, no extra LLM calls
- `ui/static/index.html` — single-file SPA (dark theme)
- Interactive step: Phase 3 (research question selection) emits a `questions` event and blocks on a `threading.Event` until `POST /api/sessions/{id}/select-question` arrives
- `run_ui.py` picks up `RUNNER_PYTHON` / `RUNNER_MAX_FIX_ATTEMPTS` from your `.env` (see `.env.example`) — point `RUNNER_PYTHON` at a GPU-enabled interpreter if training needs CUDA

---

## Directory layout

```
research-agent-lab/
├── main.py                    # CLI entry point
├── run_ui.py                  # Web UI entry point
├── download_models.py         # fetches the GGUF fallback models (see .env.example)
├── config.py                  # all paths, env vars, tuning knobs
├── router.py                  # LOCAL vs API task routing
├── requirements.txt
├── LICENSE
├── agents/
│   ├── orchestrator.py        # CLI pipeline controller
│   ├── paper_collection.py    # Phase 1
│   ├── literature_review.py   # Phase 2
│   ├── gap_analysis.py        # Phase 3
│   ├── hypothesis.py          # Phase 4
│   ├── experiment_agent.py    # Phase 5 — domain-specific codegen (Retrieval/NLP/CV/DA/RL)
│   ├── experiment_runner.py   # Phase 6 — install/pretrain/train/evaluate + auto-fix
│   ├── quality_review.py      # Phase 7 — AI-judge peer review + rubric-based checks
│   ├── report_agent.py        # Phase 8 — structured JSON research report
│   └── self_bugfix_agent.py   # retry/repair wrapper used by phases 1-6
├── models/
│   ├── ollama_model.py        # primary local backend (HTTP → Ollama server)
│   ├── local_model.py         # fallback local backend (llama-cpp-python GGUF)
│   └── api_model.py           # Claude API wrapper (cost logging, retries, local fallback)
├── memory/
│   ├── note_db.py             # SQLite: sessions, papers, hypotheses, code, runs
│   └── vector_db.py           # ChromaDB paper embeddings (CLI path only, requires Python ≤3.12)
├── tools/
│   ├── sources/               # multi-source paper search: OpenAlex, Europe PMC, Crossref, OpenReview
│   ├── rate_limit.py          # per-source 20-30 s pacing + 7-day blocks after rate limiting
│   ├── arxiv_fetcher.py
│   ├── semantic_scholar.py    # citation-sorted canon-seeding for Phase 1
│   ├── pdf_parser.py          # pymupdf → pypdf fallback
│   ├── dataset_resolver.py    # maps topic → real HF benchmark dataset
│   └── cost_tracker.py
├── ui/
│   ├── app.py                 # FastAPI app + WebSocket
│   ├── runner.py              # SessionRunner (background thread pipeline)
│   ├── report_renderer.py     # JSON → Markdown/LaTeX/PDF
│   └── static/index.html      # SPA frontend
├── tests/                      # pytest regression suite (no real API/network calls)
├── experiments/                # generated experiment codebases (hypothesis_N/)
└── data/
    ├── papers/                 # downloaded PDFs
    ├── reports/{session_id}/   # rendered report.json/.md/.tex/.pdf
    └── db/                     # research.db (SQLite) + chroma/ (ChromaDB)
```

---

## Config reference (`config.py` / `.env`)

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | required for any API-routed phase |
| `API_MODEL` | `claude-sonnet-4-5` | Claude model id |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server address |
| `OLLAMA_MODEL` | `llama3.1:8b` | tag to resolve (prefix match supported) |
| `LOCAL_MODEL_PATH` / `EMBED_MODEL_PATH` | `~/models/...gguf` | GGUF fallback paths |
| `N_GPU_LAYERS` / `EMBED_N_GPU_LAYERS` | `35` / `33` | llama-cpp GPU offload (RTX 3060 Ti tuned; `0` = CPU-only) |
| `RUNNER_PYTHON` | current interpreter | interpreter used for Phase 6 subprocesses (set to a GPU/PyTorch env if training needs CUDA) |
| `RUNNER_MAX_FIX_ATTEMPTS` | `3` | auto-fix attempts per Phase 6 script (`0` disables) |
| `RUNNER_*_TIMEOUT` | see `config.py` | per-phase subprocess timeouts, seconds; `0` = unlimited |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | embedding model for Phase 1 ranking and Phase 3 evidence/variable checks |
| `OLLAMA_NUM_CTX` | `8192` | context window sent to Ollama; a prompt that fills it raises instead of being silently truncated |
| `PAPER_SOURCES` | `arxiv,openalex,europepmc,crossref,openreview` | sources searched in Phase 1 and gap validation |
| `SOURCE_MAX_RESULTS` | `25` | results per source, per query |
| `REQUEST_INTERVAL_MIN_S` / `REQUEST_INTERVAL_MAX_S` | `20` / `30` | random spacing between requests to the same source |
| `SOURCE_BLOCK_DAYS` | `7` | days a source is left alone after it returns a rate-limit response |
| `OPENALEX_API_KEY` | — | required by OpenAlex since Feb 2026 (free); source is skipped without it |
| `CONTACT_EMAIL` | — | Crossref polite pool (`mailto`) and User-Agent contact |
| `OPENREVIEW_USERNAME` / `OPENREVIEW_PASSWORD` | — | OpenReview requires an account to read; source is skipped without it |
| `RELEVANCE_MARGIN` | `0.10` | keep papers within this cosine margin of the best match |
| `DATASET_MAX_MB` | `200` | size cap for a dataset URL found in the brief, downloaded once to read its columns for the research-question data check |
| `CANON_SEED_ENABLED` | `1` | supplement search with highly-cited papers (Phase 1) |
| `CANON_SEED_COUNT` | `5` | max canon-seeded papers per session |
| `CANON_MIN_CITATIONS` | `20` | minimum citation count to qualify as canon |
| `SEMANTIC_SCHOLAR_API_KEY` | — | optional; without it requests share one throttled anonymous pool |
| `LOG_LEVEL` | `INFO` | Python logging level |

---

## Testing

```bash
python -m pytest tests/ -v
```

53 tests, no real API or network calls (`APIModel`, `ArxivFetcher.search`, `SemanticScholarFetcher.search_top_cited` are mocked). Each file pins a specific regression:

| File | Pins |
|---|---|
| `test_gap_validation.py` | Gap-claim extraction/verification against a live arXiv search, and every degradation path (malformed JSON, failed verification call, markdown-fenced JSON) |
| `test_canon_seeding.py` | Merge/dedup/top-K-survival logic for Semantic-Scholar-sourced canon papers |
| `test_domain_routing.py` | System-prompt/file-spec domains resolve from one source (can't drift apart), and word-boundary keyword matching (`"research"` no longer false-matches `"search"`) |
| `test_cost_tracking.py` | Local-fallback calls log at $0 with a `local:` model prefix; a broken cost-tracker never crashes a successful response; `call_count(since_timestamp=...)` |
| `test_quality_review.py` | Pre-execution domain-alignment gate catches wrong-domain code without needing eval data |
| `test_baseline_literature_check.py` | Baseline-vs-literature number comparison (match/diverge/inconclusive), and that extraction never fabricates a number when the LLM honestly reports "not found" |
| `test_ai_judge_review.py` | Full expert-reviewer schema (claim ledger, cost-tag derivation/sorting, prompt-injection flagging, claims-before-results prompt ordering), backward-compat with the older output shape, graceful degradation on LLM/JSON failure |

---

## Cost tracking

Every Claude API call — and every local-model fallback call, at $0 — is logged to `data/db/research.db` (`api_usage_log` table) via `tools/cost_tracker.py`, so the table is a complete record of which backend served every request, not just a spend ledger. A summary prints at the end of a CLI session and is available at `GET /api/sessions/{id}` (`cost_usd`) in the Web UI.

Approximate cost for a typical session (Phases 3, 4, 5, 7, 8 use the API; Phases 1/2 use the local model):
- `claude-sonnet-4-5`: roughly $0.10–0.40 USD depending on paper count and experiment complexity.

---

## License

[PolyForm Noncommercial 1.0.0](LICENSE) — free for any noncommercial purpose (personal use, research, education, nonprofits). Commercial use requires a separate license from the copyright holder.

---

## Design notes

Deeper rationale for a few non-obvious pieces, kept here rather than inline above so the sections you actually need to run this stay short.

<details>
<summary><b>AI judge review (Phase 7)</b></summary>

`QualityReviewAgent._ai_judge_review()` runs an expert-reviewer protocol (`memory/EXPERT_REVIEWER_PROMPT.md`, built on `memory/PEER_REVIEW_GUIDE.md`) modeled on ARR/ICLR/NeurIPS conference reviewing, replacing a looser "simulate 2 experts, list some concerns" prompt.

- **Claim ledger before results** — the prompt presents the hypothesis's claims before the eval data and requires building a claim ledger (id, claim, scope, evidence location, actual numbers, verdict: supported/partially/contradicted/unlocatable) *before* looking at results, to block hindsight bias.
- **Eight named adversarial audits** — cross-consistency, specification-gap hunting, structural-nullification (is a claimed component mathematically incapable of an effect given its actual parameter values?), instrument-validity, statistical-power, leakage-channel separation, ablation-contradiction, and claim-scope narrowing.
- **Mandatory self-audit** against ARR's forbidden-critique list H1-H17 (hindsight bias, "not novel" without a citation, SOTA-chasing, penalizing honest disclosure) — draft weaknesses first, then delete/reclassify any that match.
- **Must-check confirmation** against ARR M/T/R/G (unmotivated sample selection, overclaiming scope, missing statistical rigor, misrepresented citations).
- **Hard constraints** — an instruction-source boundary treating any text in the reviewed code/hypothesis that addresses the judge as data, not a command (flagged in `prompt_injection_flag` if found); no fabricated citations/numbers; no claims of having run or reproduced anything; an honest `not_checked` blind-spot declaration.
- Cross-checks the hypothesis's claimed novelty against the Phase 3 gap-validation verdicts — a claim built on a gap marked `LIKELY_ADDRESSED` is flagged as an overclaiming risk.

Output: claim ledger, strengths, weaknesses (what/where/why-it-matters/fix, tagged with a 4-tier cost — `rewrite`/`reanalysis`/`re-eval`/`new_compute`), questions for the authors, Soundness/Excitement scores (1-5), an accept/borderline/major_revision/reject verdict, one sentence on what would raise the score, and the not-checked list — all surfaced in the Web UI's Review tab. Degrades gracefully to rule-based findings only on any LLM/JSON failure.
</details>

<details>
<summary><b>Baseline literature cross-check (Phase 7)</b></summary>

Real research practice compares a reproduced baseline against a specific published number, not just "did it train without crashing." `QualityReviewAgent._check_baseline_literature_match()` extracts (a) which specific number in `eval_results.json` represents the baseline's result, and (b) an explicitly-quoted comparable number from the session's collected paper abstracts — both via LLM calls instructed to return an honest "not found" rather than a guess. A >30% relative deviation is flagged `fail` (the baseline likely isn't faithful, so a "novel method beats baseline" claim built on it is untrustworthy); within tolerance is `pass`; either number missing is `warn` (inconclusive, not evidence of a problem). Never blocks the pipeline.
</details>

<details>
<summary><b>Pre-execution domain-alignment gate (between Phase 5 and 6)</b></summary>

The full Phase 7 review used to run only after Phase 6 execution, so a wrong-domain codebase (e.g. RL environment code generated for a retrieval hypothesis) wasn't caught until after burning the compute/time to run it. `QualityReviewAgent.pre_execution_check()` runs just the two checks that don't need eval results (code-domain-alignment, baseline-presence) right after Phase 5, before Phase 6 starts, and warns loudly (without blocking) on a mismatch.
</details>

<details>
<summary><b>Cost/backend logging integrity</b></summary>

An audit found `api_usage_log` had zero rows for several sessions that definitely made API calls — the likely cause: the Anthropic API silently became unavailable mid-run and `APIModel` fell back to the local model for the rest of that session, a path that logged nothing. Fixed by having `APIModel._local_fallback` log every local-model call too, at `cost_usd=0` with `model="local:<backend>"`, and wrapping the cost-log write so a DB hiccup can never crash or swallow an already-successful response. The Web UI also runs a pipeline-end healthcheck (`ui/runner.py`): if a session reaches `question_selected` or later (which requires at least 2 API-routed calls) with zero logged calls for that run, it emits a `log_integrity_warning` event.
</details>

<details>
<summary><b>Unified domain routing (Phase 5)</b></summary>

`ExperimentAgent` picks a domain-specific system prompt (steers *what* the LLM writes) and a domain-specific file spec (decides *which files* get created) per hypothesis. These used to be two separately-maintained keyword lists that had already drifted apart — one had extra keywords the other never got, so a hypothesis could get a file skeleton steered by the wrong system prompt. `_select_domain()` now returns both from a single `DomainSpec`, so they cannot disagree by construction; the resolved domain is persisted to `hypotheses.domain`. Keyword matching also moved from plain substring checks to leading-word-boundary regex (`"research"` was matching the `"search"` keyword and misrouting to the retrieval domain).
</details>

<details>
<summary><b>Phase 1 canon seeding</b></summary>

Keyword/recency-based arXiv search structurally misses highly-cited foundational papers that predate current phrasing trends. `PaperCollectionAgent` supplements arXiv results with `tools/semantic_scholar.py`, a citation-count-sorted Semantic Scholar query, and guarantees those papers survive the top-K cut regardless of how they rank on raw topic-embedding similarity. Deduplicates against the arXiv set by arXiv id and, as a fallback, normalized title. Best-effort by design — a down or rate-limited Semantic Scholar degrades to skipping canon-seeding, never blocks Phase 1.
</details>

<details>
<summary><b>Phase 3 gap validation</b></summary>

Free-generated gap claims ("no similar comparisons exist in RL") are frequently false — they describe work that already exists but wasn't in the collected paper set. Before a gap report is shown to the user or fed into research-question generation, `GapAnalysisAgent.validate_gap_report()` extracts each falsifiable claim, runs a fresh targeted arXiv search for it, and asks the LLM to render a skeptical verdict (`LIKELY_ADDRESSED` / `UNCERTAIN` / `CONFIRMED_GAP`) with cited evidence. Verdicts are appended to the gap report and persisted separately in `research_sessions.gap_validation` (JSON) for audit; question-generation is instructed to avoid building questions primarily on `LIKELY_ADDRESSED` claims. Degrades gracefully — any failure falls back to skipping/marking `UNCERTAIN` rather than blocking the pipeline.
</details>

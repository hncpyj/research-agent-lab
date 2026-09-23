# ResearchAgentLab

ResearchAgentLab is a local-first research workspace that helps turn a research
brief into literature evidence, an approved scientific question, a controlled
study, checked results, and a traceable report.

The project is also the reference implementation for **Protocol Before Code**:
a safety architecture designed to prevent an autonomous research agent from
silently implementing a different experiment from the one that was approved.

> A runnable experiment is not necessarily the intended experiment.

ResearchAgentLab is a research prototype. Generated code should be executed
only in an environment you control, and its outputs still require scientific
review.

[![ResearchAgentLab public project website](docs/assets/researchagentlab-homepage.png)](https://researchagentlab.com)

Public project site: [researchagentlab.com](https://researchagentlab.com)

---

## What it does

- Searches multiple scholarly sources and preserves source provenance.
- Extracts findings, limitations, methods, datasets, and evidence from papers.
- Challenges proposed literature gaps before turning them into research
  questions.
- Pauses for user decisions at question, hypothesis, source, and analysis-plan
  gates.
- Supports both declared-dataset studies and generated experiment codebases.
- Stores versioned artifacts so completed work can be resumed instead of
  silently regenerated.
- Routes work across local models and optional paid providers.
- Tracks provider usage, cost, degradations, retries, and operational failures.
- Produces structured results, checked claims, and Markdown/LaTeX/PDF reports.
- Separates scientific conformance from ordinary software validation.

## Current research status

The safety architecture and its motivating Choice-Set workload have been
evaluated separately. These numbers are intentionally kept distinct: safety
benchmarks do not establish the scientific hypothesis, and a successful
scientific run does not validate every safety layer.

### Safety validation

| Evaluation | Result |
|---|---:|
| Clear scientific drift accepted by intent fidelity | 0/13 |
| Any drifted protocol accepted | 0/18 |
| Faithful protocols hard-blocked | 1/16 |
| Faithful protocols escalated for review | 6/16 |
| Blind semantic apparatus mutations detected before execution | 18/18 |
| Apparatus mutations that would escape without integrity control | 15/18 |
| Faults detected in the final layered benchmark | 25/25 |
| Faults escaping the final layered benchmark | 0/25 |

These are bounded results from the recorded Choice-Set-domain evaluations and
mutation suites. They do not establish cross-domain reliability.

### Frozen Choice-Set H1 result

One frozen confirmatory run completed 192 paired units and 384 condition
records with no exclusions, fatal failures, parse failures, or model retries.

| Outcome | Benign curation | Adversarial curation | Difference | Paired-bootstrap 95% CI |
|---|---:|---:|---:|---:|
| Target selection | 25/192 (13.0%) | 52/192 (27.1%) | +14.1 pp | [+8.3, +20.3] pp |
| Explicit approval | 192/192 (100%) | 192/192 (100%) | 0.0 pp | [0.0, 0.0] pp |

The frozen H1 rule was satisfied for this candidate pool, prompt set, local
model digest, and execution schedule. Approval was at a complete ceiling, and
post-hoc mechanism diagnostics remain descriptive. No second confirmatory run
was performed.

The public evidence organization is described in
[`research_logs/README.md`](research_logs/README.md). Claim boundaries and
limitations are tracked in
[`research_logs/paper_evidence/claims.md`](research_logs/paper_evidence/claims.md).

---

## How the workflow is organized

ResearchAgentLab no longer assumes that every user needs one fixed pipeline.
Each stage declares what it requires, what it produces, and whether it is ready
to run. Existing paper lists, gap reports, and research questions can be
imported rather than regenerated; imported material is marked as such.

```text
Research brief or imported artifacts
        |
        v
Paper collection -> literature review -> gap checks -> question gate
        |
        +-- Declared-dataset study
        |      data audit -> hypothesis gate -> analysis-plan gate
        |      -> tested analysis blocks -> results -> claims -> report review
        |
        +-- Generated experiment
               hypothesis -> scientific design/build controls
               -> software preflight -> execution -> result and quality review
```

For controlled decision studies, the Protocol Before Code path is:

```text
Approved intent
    -> StudyProtocol
    -> Intent Fidelity + Methodology Review
    -> Freeze and protocol hash
    -> BuildManifest
    -> Least-authority generation
    -> Scientific Conformance
    -> Software Preflight
    -> Execution
    -> Result Conformance
    -> Claim-to-evidence review
```

The two pre-freeze reviews answer different questions:

- **Intent Fidelity:** Is this still the study that was approved?
- **Methodology Review:** Is that study scientifically defensible?

A sound design for the wrong question fails intent fidelity. A faithful but
unsound design fails methodology review. Neither verdict can override the
other.

### Least-authority execution tiers

| Tier | Model authority |
|---|---|
| Declarative | Trusted apparatus runs the study; the model supplies bounded structured content. |
| Plugin | Trusted infrastructure remains fixed; the model implements a declared interface. |
| Open-ended | The model may generate the program when no constrained representation is available. |

Trusted apparatus is bound to the `BuildManifest` by content hash, not only by
filename or interface. Scientific changes require a new protocol version;
software repair is not allowed to redefine the frozen science.

---

## Quick start

### Requirements

- Python 3.12 is recommended.
- Git is recommended for provenance and reproducibility.
- [Ollama](https://ollama.com/) is optional but is the simplest local model
  backend.
- A paid-provider key is optional. The application can run local-only when a
  suitable local model is available.

### Install

```bash
git clone https://github.com/hncpyj/research-agent-lab.git
cd research-agent-lab
python -m venv .venv
```

Activate the environment:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Install the Python dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Optional local models

```bash
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

The first model handles local text generation. `nomic-embed-text` is used for
paper relevance ranking. Model names and the context window can be changed in
the application settings or `.env`.

### Configuration

Copy `.env.example` to `.env` and set only the backends you intend to use.
Never commit `.env` or provider keys.

```bash
# macOS / Linux
cp .env.example .env

# Windows PowerShell
Copy-Item .env.example .env
```

Supported adapter types:

| Backend | Configuration |
|---|---|
| Ollama | `OLLAMA_HOST`, `OLLAMA_MODEL`, `OLLAMA_EMBED_MODEL` |
| llama.cpp GGUF fallback | `LOCAL_MODEL_PATH`, `EMBED_MODEL_PATH` |
| Anthropic | `ANTHROPIC_API_KEY`, `API_MODEL` |
| OpenAI | `OPENAI_API_KEY`, `OPENAI_MODEL` |
| Gemini | `GEMINI_API_KEY`, `GEMINI_MODEL` |
| OpenAI-compatible local server | Configure its URL and model in Settings |

An adapter being present does not guarantee that a particular account or model
identifier is available. Validate paid-provider configuration with one minimal
canary before relying on it for a run. Do not use scientific experiments as
provider integration tests.

### Run the application

```bash
python run_ui.py
```

The application opens at `http://127.0.0.1:8000`.

Useful options:

```bash
python run_ui.py --no-browser
python run_ui.py --port 8080
python run_ui.py --reload
```

`run_ui.py` refuses to bind to a non-loopback address without `UI_TOKEN`
unless `--allow-insecure` is explicitly supplied. Do not use
`--allow-insecure` on an untrusted network.

### CLI

The original CLI remains available:

```bash
python main.py
python main.py --topic "your research topic"
python main.py --session <session_id>
python main.py --list-sessions
python main.py --skip-local
python main.py --session <session_id> --experiment
python main.py --session <session_id> --run-experiment
```

The Web UI and CLI share the same SQLite store and can resume the same session.

---

## Model routing and cost controls

Structured, repetitive tasks can be routed to a local model while tasks that
require broader synthesis use the configured API provider. When API use is
disabled or unavailable, eligible calls fall back to the local backend and the
degradation is recorded rather than hidden.

Provider calls and local fallbacks are written to the usage log with backend,
token, cost, and timing information. `API_DAILY_BUDGET_USD` can cap paid use;
`0` means no application-level cap. Unknown model prices remain marked unknown
instead of being silently assigned an incorrect cost.

ResearchAgentLab currently provides no managed model credits. Hosted users must
provide their own provider key, and local users can choose local-only mode.

---

## Data, privacy, and execution safety

- Session state and versioned artifacts are stored in SQLite under `DATA_DIR`.
- User-supplied provider keys stored by the application are encrypted at rest.
- `.env`, local databases, raw experimental outputs, private notes, caches, and
  active run directories are excluded from version control.
- Dataset downloads reject loopback and private-network targets. Public-host
  access can be narrowed with `DATASET_ALLOWED_HOSTS`.
- Generated dependency entries that are URLs, paths, or pip options are
  refused. Set `RUNNER_ALLOW_PIP=0` to disable generated package installation.
- Hosted mode disables model-written code execution by default. Set
  `ALLOW_CODE_EXECUTION=1` only when the runner is isolated from the host and
  other users.

Before staging changes, inspect the complete Git snapshot—not only the current
diff—to ensure raw data, credentials, private reviews, and local research notes
are not included.

---

## Repository layout

```text
research-agent-lab/
├── agents/          research agents, protocol lifecycle, gates, manifests
├── memory/          SQLite persistence, accounts, encrypted keys, provenance
├── models/          Ollama, llama.cpp, and paid-provider adapters
├── tools/           scholarly sources, analysis blocks, runners, logging
├── ui/              FastAPI application and working single-page interface
├── web/             separate static public website
├── tests/           deterministic regression and safety tests
├── research_logs/   public benchmark, baseline, taxonomy, and claims records
├── main.py          CLI entry point
├── run_ui.py        application entry point
├── config.py        environment-backed configuration
└── DEPLOYMENT.md    hosting and security guidance
```

Generated studies, datasets, databases, raw logs, confirmatory packages, and
private working files are intentionally not part of the public source tree.

---

## Testing

Run the deterministic suite:

```bash
python -m pytest -q
```

The suite covers, among other areas:

- protocol lifecycle, hashes, intent identity, and methodology gates;
- trusted-apparatus and candidate-pool integrity;
- scientific and result conformance;
- exposure, contamination, prompt-injection, and path safety;
- provider adapters, cost tracking, rate limits, and local fallback;
- account ownership, encrypted keys, backups, and restart recovery;
- declared-dataset audits, analysis plans, results, and claim checks;
- generated-code preflight, repair boundaries, and hosted-mode restrictions.

Provider canaries and scientific experiments are not unit tests. Run and label
them separately, preserve their raw records, and never promote pilot or
post-hoc results to confirmatory evidence.

---

## Deployment

The repository contains two deployable surfaces:

- `web/` is a static public website.
- The Python application is a long-running, stateful FastAPI service with
  WebSockets and persistent storage.

Do not deploy the React design-reference application screens as if they were
live account data. Do not enable generated-code execution on a shared host
without an isolated runner. See [`DEPLOYMENT.md`](DEPLOYMENT.md) for the current
container, storage, proxy, account, and security requirements.

---

## Research and evidence discipline

Meaningful research changes are classified, measured against a named baseline,
recorded with raw evidence, and connected to a claims ledger. Development,
pilot, confirmatory, provider-integration, and post-hoc results remain separate.

See:

- [`research_logs/README.md`](research_logs/README.md) — evidence workflow
- [`research_logs/baselines.md`](research_logs/baselines.md) — preserved baselines
- [`research_logs/taxonomy.md`](research_logs/taxonomy.md) — failure taxonomy
- [`research_logs/paper_evidence/claims.md`](research_logs/paper_evidence/claims.md) — claim boundaries

## Known boundaries

- The strongest intent-fidelity evidence is currently in the Choice-Set domain.
- The completed Choice-Set result uses one candidate pool and one local model
  digest; it is not evidence about real users or all autonomous agents.
- Explicit approval was at ceiling in the confirmatory run.
- A full cross-family free-form-versus-constrained SSFR comparison remains
  future work.
- Local execution is not a security sandbox.
- Paid-provider availability, model aliases, and pricing can change outside
  this repository.

## License

[PolyForm Noncommercial 1.0.0](LICENSE). Noncommercial use—including personal,
academic, educational, and nonprofit research—is permitted. Commercial use
requires a separate license from the copyright holder.

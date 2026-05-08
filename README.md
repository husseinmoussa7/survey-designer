# Survey Designer Agent

A multi-agent system that automatically designs consumer research surveys from academic hypotheses. Given a set of research hypotheses, the pipeline produces a polished, deployment-ready survey through iterative critique, discussion, and revision by four specialized AI agents.

---

## System Overview

Four agents collaborate in sequence:

| Agent | Model | Role |
|-------|-------|------|
| **Converter** | gpt-4o-mini | Parses hypotheses and drafts the initial survey (v0) |
| **Editor** | gpt-4o | Improves question wording, scales, and construct coverage across 3 parallel runs |
| **Critic** | gpt-4o | Identifies validity threats and wording problems; issues severity-rated critique |
| **Econometrician** | gpt-4o | Validates statistical design, scale balance, and order effects |

---

## Pipeline Flow

```
hypotheses.txt
     │
     ▼
[Step 1] Converter ──────────────────────────► survey_v0
     │
     ▼
[Step 2] Editor × 3 parallel runs
         scored merge (n_q + types×2) ────────► best_survey
     │
     ▼
[Step 3] Critic + Editor discussion
         2 rounds of feedback ─────────────────► post_meeting_survey
     │
     ▼
[Step 4] Critic formal review ──────────────────► critique (severity 1–3)
     │
     ├─► [4a] Editor fixes severity-3 issues
     ├─► [4b] Editor fixes severity-2 issues
     └─► [4c] Editor fixes severity-1 issues
     │
     ▼
[Step 5] Econometrician review ─────────────────► ai_survey.json
```

---

## Quickstart

### 1. Install

```bash
git clone https://github.com/husseinmoussa7/survey-designer-agent.git
cd survey-designer-agent
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env — at minimum set OPENAI_API_KEY
```

### 3. Run one paper

```bash
# Run the full pipeline on a test paper
python scripts/run_paper.py --paper papers/test/02_ShaniFeinstein_2022_MovingFastSlow/Study_1

# With cross-paper training memory injected (recommended for test papers)
python scripts/run_paper.py --paper papers/test/02_ShaniFeinstein_2022_MovingFastSlow/Study_1 --cross-memory
```

Output is written to `results/<project_name>/` and a session memory file to `memory/`.

### 4. Evaluate

```bash
# Evaluate one paper against its ground-truth survey
python scripts/evaluate.py --paper 02

# Evaluate all papers
python scripts/evaluate.py --all
```

### 5. Populate training memory (batch)

```bash
# Run the full pipeline on all training papers
python scripts/run_batch.py
```

---

## Training vs. Test Paper Split

The corpus contains **42 papers** from top marketing journals. Ten papers are held out as a test set and never used to populate training memory:

| Set | Papers | Count |
|-----|--------|-------|
| Training | All others | 32 |
| Test | 02, 04, 08, 16, 20, 25, 33, 37, 41, 42 | 10 |

Training papers are in `papers/training/`; test papers in `papers/test/`. The split is enforced by `scripts/run_batch.py`, which skips test papers, and by `SURVEY_CROSS_MEMORY_TRAINING_ONLY=1` in `.env`, which filters test sessions from cross-paper memory injection.

---

## Memory System

Every run writes a session file to `memory/{project}_{YYYYMMDD}_{HHMMSS}.json` capturing the survey state after every pipeline step. Memory enables:

- **Crash recovery** — checkpoint written after each step; rerunning the same paper resumes from the last completed step
- **Cross-paper learning** — training sessions can be injected as few-shot context into Step 2 of new runs (`SURVEY_CROSS_MEMORY=1`)
- **Export** — `export/` scripts read memory files to produce Word reports

See [docs/MEMORY_SCHEMA.md](docs/MEMORY_SCHEMA.md) for the full JSON schema.

---

## Web UI

A Flask server lets you process a raw survey text interactively:

```bash
python server/app.py
# Open http://localhost:5000
```

Paste your survey text into the interface and the pipeline runs end-to-end in the browser.

---

## Export Reports

Three export scripts produce Word documents from session memory:

```bash
# Before/after comparison (v0 vs. final)
python export/before_after.py --project shani_feinstein_2022_study_1

# Critique with revisions annotated
python export/critique_report.py --project shani_feinstein_2022_study_1

# Memory summary report across all sessions
python export/memory_reports.py
```

---

## Repository Structure

```
survey-designer-agent/
├── pipeline/
│   ├── __init__.py
│   └── flow.py              # SurveyEnhancementFlow — full 5-step pipeline
│
├── config/
│   ├── agents/              # CrewAI agent definitions (YAML)
│   └── tasks/               # CrewAI task definitions (YAML)
│
├── scripts/
│   ├── run_paper.py         # Run pipeline on a single paper
│   ├── run_batch.py         # Run pipeline on all training papers
│   └── evaluate.py          # Evaluate AI survey vs. ground truth
│
├── export/
│   ├── memory_reports.py    # Word report: memory summary
│   ├── before_after.py      # Word report: v0 vs. final comparison
│   └── critique_report.py   # Word report: critique with revisions
│
├── server/
│   ├── app.py               # Flask web server
│   └── static/              # survey.html, survey_v2.html
│
├── papers/
│   ├── training/            # 32 training papers (hypotheses.txt only)
│   └── test/                # 10 held-out test papers
│
├── knowledge/               # Place reference PDFs here (gitignored)
├── memory/                  # Session JSON files (auto-generated)
├── results/                 # Evaluation outputs
│
├── knowledge_sources.py     # CrewAI knowledge source loader
├── docs/
│   ├── PIPELINE_OVERVIEW.md
│   └── MEMORY_SCHEMA.md
└── .env.example
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | Required for all agents |
| `ANTHROPIC_API_KEY` | — | Optional alternative LLM backend |
| `PAPERS_DIR` | `papers` | Path to directory containing training/test papers |
| `SURVEY_CROSS_MEMORY` | `0` | Set to `1` to inject training memory into Step 2 |
| `SURVEY_CROSS_MEMORY_MAX` | `20` | Max number of other sessions to inject |
| `SURVEY_CROSS_MEMORY_TRAINING_ONLY` | `1` | Exclude test paper sessions from cross-memory |
| `KNOWLEDGE_DIR` | `knowledge` | Directory containing reference PDFs for agents |
| `QUALTRICS_API_TOKEN` | — | Required for Qualtrics survey deployment |
| `MTURK_SANDBOX` | `True` | Set to `False` for real MTurk HITs |

---

## Citation

If you use this system in your research, please cite:

```
@software{survey_designer_agent,
  author  = {Hussein Moussa},
  title   = {Survey Designer Agent: Multi-Agent Survey Design for Consumer Research},
  year    = {2024},
  url     = {https://github.com/husseinmoussa7/survey-designer-agent}
}
```

---

## License

MIT License. See [LICENSE](LICENSE).

The `papers/` directory contains hypotheses excerpted for research purposes. Original papers are copyrighted by their respective publishers. No full-text PDFs are distributed.

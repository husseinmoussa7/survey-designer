# Survey Designer Agent

Designing a valid survey from a research hypothesis is slow expert work: picking the constructs, wording items that don't lead the respondent, matching scales across questions, and adding the manipulation and attention checks a reviewer will ask for. This repository tests whether a multi-agent pipeline can approximate that work when given only the hypotheses. The benchmark is a corpus of 42 published marketing papers whose instruments are known, with 10 papers held out; pipeline output is scored against the published survey. The goal is to measure the size of the gap, not to claim it is closed.

---

## Results

**Status: 1 of the 10 held-out test papers has been evaluated so far.** The headline number is therefore n = 1, not n = 10, and should be read as such.

On paper 02 (Shani & Feinstein 2022, *JCR*), the generated survey scored **4.15 / 5 mean wording quality** and **83% construct coverage**, against **50%** for the published human survey on the same judge-scored rubric. Both scores come from a GPT-4o judge, so they measure agreement with a model's view of survey methodology, not with the papers' actual results.

What it does well: wording is consistently clean (10 of 13 questions scored 4 or 5), and the pipeline reliably adds manipulation checks, attention checks, and consistent 1–7 scales — the published survey in this case had none of the first two. Where it fails: coverage is thin. It produced 13 questions against the human survey's 25, omitted demographics entirely (1/3), and its own critic still flagged two severity-3 survey-level gaps in the final output — no validated construal-level scale and no mediator or moderator measures.

The nine remaining test papers have not been run. See [results/HELDOUT_EVALUATION.md](results/HELDOUT_EVALUATION.md) for per-paper status, the full metric breakdown, and the commands to complete the evaluation.

### Train/test discipline

The ten test papers are held out of the cross-paper memory system, not just out of the training loop. `load_cross_paper_training_context()` in `pipeline/flow.py` drops any saved session whose paper ID is in `TEST_PAPERS` whenever `SURVEY_CROSS_MEMORY_TRAINING_ONLY=1` (the default), and `scripts/run_batch.py` skips those papers when populating memory. A held-out paper is therefore designed using lessons from training papers only — no test paper's output is ever injected as few-shot context into another run, so the held-out scores are not contaminated by the memory system.

---

## System Overview

Four agents collaborate in sequence:

| Agent | Model | Role |
|-------|-------|------|
| **Converter** | gpt-4o-mini | Parses hypotheses and drafts the initial survey (v0) |
| **Editor** | gpt-4o | Improves question wording, scales, and construct coverage across 3 parallel runs |
| **Critic** | gpt-4o | Identifies validity threats and wording problems; issues severity-rated critique |
| **Reviser** | gpt-4o | Applies critic feedback — during the discussion rounds and the severity-driven fix passes |

The Converter, Editor, and Critic have declarations in `config/agents/`; the Reviser is defined inline in `pipeline/flow.py` (as `enhancement_agent`) with its task in `config/tasks/enhance_survey_iteratively.yaml`. All four are instantiated by `SurveyEnhancementFlow._load_agents()`.


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
[Step 3] Critic + Reviser discussion
         2 rounds of feedback ─────────────────► post_meeting_survey
     │
     ▼
[Step 4] Critic formal review ──────────────────► critique (severity 1–3)
     │
     ├─► [4a] Reviser fixes severity-3 issues
     ├─► [4b] Reviser fixes severity-2 issues
     └─► [4c] Reviser fixes severity-1 issues ─► ai_survey.json
```

---

## Quickstart

### 1. Install

```bash
git clone https://github.com/husseinmoussa7/survey-designer.git
cd survey-designer
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
python scripts/run_paper.py --paper papers/test/02_ShaniFeinstein_2022_MovingFastSlow

# With cross-paper training memory injected (recommended for test papers)
python scripts/run_paper.py --paper papers/test/02_ShaniFeinstein_2022_MovingFastSlow --cross-memory
```

Pass the study subdirectory (e.g. `papers/test/33_Kyung_2025_ScaleOrientationEffect/Experiment 1a`) for papers that split hypotheses across studies; pass the paper directory itself for those that don't.

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
python export/before_after.py --project shani_feinstein_2022

# Critique with revisions annotated
python export/critique_report.py --project shani_feinstein_2022

# Memory summary report across all sessions
python export/memory_reports.py
```

---

## Repository Structure

```
survey-designer/
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
  url     = {https://github.com/husseinmoussa7/survey-designer}
}
```

---

## License

MIT License. See [LICENSE](LICENSE).

The `papers/` directory contains hypotheses excerpted for research purposes. Original papers are copyrighted by their respective publishers. No full-text PDFs are distributed.

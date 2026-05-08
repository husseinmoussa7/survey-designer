# Pipeline Overview

The survey designer pipeline transforms a set of research hypotheses into a polished, deployment-ready survey through five sequential steps, each handled by one or more CrewAI agents.

---

## End-to-End Flow

```
hypotheses.txt
     │
     ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 1 — Convert                                               │
│  Agent: survey_convert_agent (gpt-4o-mini)                      │
│  Task:  convert_survey_to_json                                   │
│                                                                  │
│  Reads hypotheses → drafts initial v0 survey (JSON)             │
│  Output: survey_v0 saved to session memory                       │
└───────────────────────────┬─────────────────────────────────────┘
                            │ survey_v0
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 2 — Parallel Enhancement (3 × independent runs)           │
│  Agent: survey_editor (gpt-4o)                                  │
│  Task:  enhance_survey_iteratively                               │
│                                                                  │
│  Run A ──┐                                                       │
│  Run B ──┼──► scored merge ──► best_survey                       │
│  Run C ──┘   (n_q + types*2)                                     │
│                                                                  │
│  Optional: inject cross-paper training memory as context         │
│  Output: best_survey saved to session memory                     │
└───────────────────────────┬─────────────────────────────────────┘
                            │ best_survey
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 3 — Meeting Discussion (2 rounds)                          │
│  Agents: survey_editor + survey_critic_agent                     │
│                                                                  │
│  Round 1: Critic reviews → Editor responds → revised survey      │
│  Round 2: Critic reviews again → Editor responds → final survey  │
│                                                                  │
│  Output: post_meeting_survey saved to session memory             │
└───────────────────────────┬─────────────────────────────────────┘
                            │ post_meeting_survey
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 4 — Formal Critique                                        │
│  Agent: survey_critic_agent (gpt-4o)                            │
│  Task:  critique_survey_task                                     │
│                                                                  │
│  Produces structured critique: list of issues, each with:        │
│    • severity (1–3)                                              │
│    • description                                                 │
│    • suggested fix                                               │
│                                                                  │
│  Output: critique saved to session memory + critique.json        │
└───────────────────────────┬─────────────────────────────────────┘
                            │ critique
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 4a — Severity-3 Revisions (critical issues only)          │
│  STEP 4b — Severity-2 Revisions                                  │
│  STEP 4c — Severity-1 Revisions (minor polish)                   │
│  Agent: survey_editor (gpt-4o)                                  │
│                                                                  │
│  Each pass applies one severity tier of critique items           │
│  Output: revised_survey after each pass                          │
└───────────────────────────┬─────────────────────────────────────┘
                            │ final_survey
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 5 — Econometrician Review                                  │
│  Agent: econometrician_agent (gpt-4o, code execution enabled)   │
│                                                                  │
│  Reviews for statistical validity, scale balance, order effects  │
│  Output: final_survey_v1 saved as ai_survey.json                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Session Memory

Every run writes a session file at `memory/{project}_{YYYYMMDD}_{HHMMSS}.json` that records the output of every step. This enables:

- **Resume after crash**: checkpoint written after each step; pipeline skips completed steps on restart
- **Cross-paper training**: other sessions' summaries can be injected into Step 2 as prior knowledge
- **Export**: `export/` scripts read memory files to produce Word reports

See [MEMORY_SCHEMA.md](MEMORY_SCHEMA.md) for the full JSON schema.

---

## Agent Roles

| Agent | Model | Role |
|-------|-------|------|
| `survey_convert_agent` | gpt-4o-mini | Parses hypotheses and produces the first structured draft |
| `survey_editor` | gpt-4o | Iteratively improves question wording, scales, and coverage |
| `survey_critic_agent` | gpt-4o | Identifies gaps, validity threats, and wording problems |
| `econometrician_agent` | gpt-4o | Validates statistical and experimental design properties |

---

## Cross-Paper Training Memory

When `SURVEY_CROSS_MEMORY=1`, Step 2 loads up to `SURVEY_CROSS_MEMORY_MAX` session summaries from other papers in `memory/`. These summaries act as few-shot examples showing the editor what a good enhanced survey looks like for a different paper.

By default (`SURVEY_CROSS_MEMORY_TRAINING_ONLY=1`), test paper sessions are excluded from the injected context, preserving the integrity of held-out evaluations.

---

## Checkpoint and Resume

A checkpoint file `{project}_checkpoint.json` in the working directory is written after each step. If the pipeline is interrupted, rerunning `scripts/run_paper.py` on the same paper will detect the checkpoint and skip already-completed steps, resuming from the last successful step.

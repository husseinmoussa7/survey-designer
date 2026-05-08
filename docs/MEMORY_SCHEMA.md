# Memory Schema

Each pipeline run writes a session file to `memory/{project}_{YYYYMMDD}_{HHMMSS}.json`.

---

## Top-Level Structure

```json
{
  "project":         "string  — folder name used as identifier (e.g. shani_feinstein_2022_study_1)",
  "hypothesis_text": "string  — full text of the hypotheses.txt file",
  "timestamp":       "string  — ISO 8601 start time",
  "steps": { ... },
  "summary":         "string  — one-paragraph summary written after Step 5 (may be null)"
}
```

---

## `steps` Object

Each key is a step identifier. Steps are written incrementally; later steps are absent if the pipeline was interrupted.

```json
{
  "step1_convert":          { ... },
  "step2_enhance":          { ... },
  "step3_meeting":          { ... },
  "step4_critique":         { ... },
  "step4a_revise_sev3":     { ... },
  "step4b_revise_sev2":     { ... },
  "step4c_revise_sev1":     { ... },
  "step5_econometrician":   { ... }
}
```

### Step 1 — `step1_convert`

```json
{
  "survey_v0": {
    "title":     "string",
    "questions": [ <Question>, ... ]
  }
}
```

### Step 2 — `step2_enhance`

```json
{
  "parallel_runs": [
    { "run_id": 0, "survey": <Survey>, "score": 42 },
    { "run_id": 1, "survey": <Survey>, "score": 38 },
    { "run_id": 2, "survey": <Survey>, "score": 45 }
  ],
  "best_run_id": 2,
  "best_survey":  <Survey>,
  "cross_memory_injected": true
}
```

### Step 3 — `step3_meeting`

```json
{
  "rounds": [
    {
      "round": 1,
      "critic_feedback": "string",
      "editor_response":  "string",
      "revised_survey":   <Survey>
    },
    {
      "round": 2,
      "critic_feedback": "string",
      "editor_response":  "string",
      "revised_survey":   <Survey>
    }
  ],
  "post_meeting_survey": <Survey>
}
```

### Step 4 — `step4_critique`

```json
{
  "critique": {
    "issues": [
      {
        "id":          1,
        "severity":    3,
        "description": "string — what is wrong",
        "fix":         "string — suggested change"
      },
      ...
    ],
    "summary": "string — overall assessment"
  }
}
```

**Severity scale:**
- `3` — Critical: threatens construct validity or data usability
- `2` — Moderate: reduces quality but survey is still usable
- `1` — Minor: wording or formatting polish

### Steps 4a / 4b / 4c — `step4a_revise_sev3`, etc.

```json
{
  "issues_addressed": [ 1, 3, 5 ],
  "revised_survey":   <Survey>
}
```

### Step 5 — `step5_econometrician`

```json
{
  "econometrician_notes": "string — free-text review",
  "final_survey":         <Survey>
}
```

---

## `<Survey>` Object

```json
{
  "title":       "string",
  "description": "string (optional)",
  "questions": [ <Question>, ... ]
}
```

## `<Question>` Object

```json
{
  "id":           "string  — e.g. Q1, Q2a",
  "text":         "string  — question stem",
  "type":         "string  — one of: likert, multiple_choice, open_ended, matrix, slider, ranking",
  "scale":        "string  — scale label if applicable (e.g. '1=Strongly Disagree, 7=Strongly Agree')",
  "options":      [ "string", ... ],
  "construct":    "string  — the latent construct this item measures",
  "hypothesis":   "string  — e.g. H1, H2 (which hypothesis this item is tied to)"
}
```

---

## Scoring Formula (Step 2 merge)

The `score` field for each parallel run is computed as:

```
score = n_questions + (n_unique_types * 2)
```

where `n_unique_types` counts the number of distinct `type` values across all questions. This rewards both breadth (more questions) and diversity (varied measurement approaches).

---

## Cross-Paper Memory Injection

When `SURVEY_CROSS_MEMORY=1`, `SurveyEnhancementFlow.load_cross_paper_training_context()` reads up to `SURVEY_CROSS_MEMORY_MAX` other session files from `memory/`. For each session it uses the `summary` field. Test paper sessions (whose project names begin with test paper IDs like `02`, `04`, ...) are filtered out when `SURVEY_CROSS_MEMORY_TRAINING_ONLY=1`.

---

## Example

```json
{
  "project": "shani_feinstein_2022_study_1",
  "hypothesis_text": "H1: As perceived movement speed increases from slow to fast, ...",
  "timestamp": "2024-10-27T14:32:01",
  "steps": {
    "step1_convert": {
      "survey_v0": {
        "title": "Movement Speed and Consumer Preference Survey",
        "questions": [
          {
            "id": "Q1",
            "text": "How fast did the object appear to be moving?",
            "type": "likert",
            "scale": "1=Very Slow, 7=Very Fast",
            "construct": "perceived_movement_speed",
            "hypothesis": "H1"
          }
        ]
      }
    }
  },
  "summary": "A 24-item survey covering perceived movement speed (H1), construal level (H2), ..."
}
```

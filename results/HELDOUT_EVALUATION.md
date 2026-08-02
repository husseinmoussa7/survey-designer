# Held-Out Test Set Evaluation

Status of the 10-paper held-out evaluation, the metrics behind the headline number in the
[README](../README.md#results), and what remains to be run.

**Current status: 1 of 10 test papers evaluated.**

---

## Per-paper status

| # | Paper | Pipeline run | Evaluation on disk |
|---|-------|--------------|--------------------|
| 02 | Shani & Feinstein (2022), *Moving Fast and Slow* — JCR | yes | yes — `results/shani_feinstein_2022/` |
| 04 | Fei (2025), *Mental Representation of Expenditures* | no | no |
| 08 | Buechel (2023), *Mysterious Consumption* | no | no |
| 16 | Shalev (2025), *Search or Scroll* | no | no |
| 20 | Palmeira (2025), *The Confidence Trap* | no | no |
| 25 | Goenka (2025), *Price Partitioning & Socio-Moral Surcharges* | no | no |
| 33 | Kyung (2025), *Scale Orientation Effect* | no | no |
| 37 | Davis (2025), *Mixed Couples & Brand Outcomes* | no | no |
| 41 | Sun & Pham (2025), *Special Consumption Experiences* | no | no |
| 42 | Bergner (2023), *Machine Talk* | no | no |

The 24 numbered sessions in `memory/` are training papers, used to populate cross-paper memory.
Only paper 02 among the held-out set has been run through the pipeline.

---

## What `scripts/evaluate.py` computes

Five metrics per paper. Metrics 2 and 3 are GPT-4o judge calls at `temperature=0`; the rest are
counted directly from the survey JSON and the critic's output.

| Metric | Source | Output |
|--------|--------|--------|
| 1. Question count & type distribution | counted from survey JSON | counts per `input_type` |
| 2. Construct coverage | GPT-4o judge, given hypotheses + AI questions | 0–3 per construct, plus an overall coverage % |
| 3. Wording quality | GPT-4o judge, given AI questions only | 1–5 per question, mean, list below 3 |
| 4. Scale consistency | counted from `input_config` | scale ranges, whether endpoints agree |
| 5. Critic issue summary | counted from the run's `critique` object | issue counts by severity, issues per question |

**Ground truth is not distributed with this repo.** The published instruments live in the papers'
supplementary appendices, which are copyrighted and mostly paywalled, so they cannot be
redistributed here. `results/**/ground_truth_text.txt` and `results/**/*.pdf` are gitignored. What
this repository ships is the input side (short statements of each paper's hypotheses), the
pipeline's own output, and derived measurements — never the published survey text. Anyone
reproducing the AI-vs-human comparison has to obtain the appendices themselves; see
`results/shani_feinstein_2022/README.md` for the procedure on paper 02.

**Caveat on comparability.** The stored report for paper 02 contains human-survey columns
(`human_question_count`, `human_score`, `overall_coverage_human`). Those came from an earlier
evaluation run that had the paywalled supplementary PDF available as ground truth. The current
`scripts/evaluate.py` does not load a ground-truth survey — it leaves `human_question_count` as
`null` and sets `ground_truth_available: false`. Re-running `--paper 02` today reproduces the
AI-side scores but not the human comparison. Any AI-vs-human number added for the remaining nine
papers needs the ground-truth instrument supplied the same way (see
`results/shani_feinstein_2022/README.md` for the procedure).

---

## Paper 02 — full breakdown

Source: `results/shani_feinstein_2022/evaluation_report.json`.

### Metric 1 — Question count and types

| | AI | Human |
|---|---|---|
| Total questions | 13 | 25 |
| scale | 5 | 12 |
| multiple_choice | 4 | 4 |
| matrix | 3 | 0 |
| open_text / text_input | 1 | 5 |
| manipulation_check | 0 (inline) | 2 |
| attention_check | 0 (inline) | 2 |

The AI survey produced roughly half the items of the published instrument. It does include a
manipulation check and an attention check, but as ordinary typed questions rather than as
separately labelled item types, which is why those rows read 0.

### Metric 2 — Construct coverage (0–3)

| Construct | AI | Human |
|---|---|---|
| Speed manipulation | 2 | 2 |
| Construal level | 3 | 1 |
| Preference measurement | 3 | 2 |
| Manipulation checks | 3 | 1 |
| Attention checks | 3 | 0 |
| Demographics | 1 | 3 |
| **Overall** | **83%** | **50%** |

Missing in AI: demographic items. Present in AI but not in the human survey: explicit
construal-level measurement, manipulation checks, attention checks.

The 83-vs-50 result should be read carefully. It says the AI survey covers more of the constructs
*the judge derived from the stated hypotheses* — it does not say the AI survey would have
supported the paper's actual analyses. The published instrument spends items on demographics and
on study-specific materials that the judge's construct list does not ask about.

### Metric 3 — Wording quality (1–5)

Mean **4.15 / 5** as recorded by the judge; the mean recomputed over the 13 listed per-question
scores is 4.08.

| Score | Questions |
|---|---|
| 5 | q5a, q7, q8, q9, q10 |
| 4 | q1, q2, q3, q4b, q5 |
| 3 | q4, q4c |
| 2 | q6 |

10 of 13 questions scored 4 or 5. The single failure, q6, was flagged as leading and confusing.

### Metric 4 — Scale consistency

5 scale questions, all 1–7, consistent within the AI survey. The published survey mixes 1–7,
1–11, and 1–5 scales, so consistency here is a difference in style, not strictly an improvement.

### Metric 5 — Critic issues in the final output

| | Count |
|---|---|
| Question-level issues | 14 |
| — severity 3 (must fix) | 1 |
| — severity 2 (moderate) | 11 |
| Survey-level issues | 4 |
| — severity 3 | 2 |
| Issues per question | 1.08 |

This is the most useful honest signal in the run: after all three severity-driven fix passes, the
system's own critic still rates two survey-level problems as must-fix — no validated
construal-level scale, and no measurement of mediators or moderators. The pipeline reliably
cleans up wording, and does not reliably close theoretical gaps.

---

## Completing the evaluation

For each remaining test paper, run the pipeline with cross-paper memory, then evaluate:

```bash
python scripts/run_paper.py --paper papers/test/04_Fei_2025_MentalRepresentationExpenditures --cross-memory
python scripts/evaluate.py --paper 04
```

and likewise for 08, 16, 20, 25, 33, 37, 41, 42. Paper 33 splits its hypotheses across seven
experiment subdirectories — pass one of them (e.g. `.../33_Kyung_2025_ScaleOrientationEffect/Experiment 1a`)
to keep the test set at one run per paper.

Evaluation reports are written to `results/evaluations/<project>_evaluation.{json,docx}`.

`SURVEY_CROSS_MEMORY_TRAINING_ONLY=1` must stay set (it is the default) so that test-paper
sessions accumulated along the way are not injected into later test-paper runs.

### Expected API cost

Per paper, the pipeline issues roughly 12 GPT-4o calls (3 parallel edits + 1 merge, 2 discussion
rounds × 2 calls, 1 formal critique, up to 3 severity fix passes) plus one GPT-4o-mini conversion
call, and evaluation adds 2 GPT-4o calls. At list pricing ($2.50 / 1M input, $10 / 1M output) and
assuming ~6k input / ~1.5k output tokens per call — the input side is inflated by up to 20
injected training summaries — that is roughly **$0.40–0.80 per paper**, so **about $4–7 to run
and evaluate the remaining nine**. Treat this as an order-of-magnitude figure; actual cost scales
with how many severity-rated issues the critic raises, since each fix pass is an extra call.

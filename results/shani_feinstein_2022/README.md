# Results — Shani & Feinstein (2022)

This directory contains the evaluation outputs for the held-out test paper:

> Shani, Y., & Feinstein, R. (2022). Moving fast and slow: How perceived movement speed shapes consumer judgment. *Journal of Consumer Research*.

## Files

| File | Description |
|------|-------------|
| `ai_survey.json` | Final enhanced survey (JSON) produced by the pipeline |
| `critique.json` | Critic agent's structured critique output |
| `evaluation_report.json` | Quantitative evaluation scores against the ground-truth survey |
| `evaluation_report.md` | Human-readable evaluation summary |

The two report files contain only derived measurements — counts, judge scores, and critique of the
pipeline's own output. No text from the published instrument is reproduced in them.

## Not included: the ground truth

Two files are deliberately absent from this repository, both derived from the article's
supplementary data, which is a paywalled journal supplement:

| File | What it is |
|------|-----------|
| `ucac004_supplementary_data.pdf` | The Web Appendix as published |
| `ground_truth_text.txt` | A plaintext extraction of that PDF |

Neither is redistributable, so neither is tracked here; both are gitignored. The evaluation
numbers in `evaluation_report.json` are derived from them but do not reproduce them.

To replicate the evaluation:

1. Access the article via your institution: `https://doi.org/10.1093/jcr/ucac004`
2. Download the supplementary data PDF
3. Place it in this directory as `ucac004_supplementary_data.pdf`
4. Extract it to `ground_truth_text.txt` in this directory
5. Run `python scripts/evaluate.py --paper 02`

The same constraint applies to every other paper in the corpus, which is why the held-out
evaluation cannot ship as a self-contained benchmark — see
[../HELDOUT_EVALUATION.md](../HELDOUT_EVALUATION.md).

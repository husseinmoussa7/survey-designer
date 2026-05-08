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
| `ground_truth_text.txt` | Plaintext extract of the published survey items used as ground truth |

## Missing File: `ucac004_supplementary_data.pdf`

The full supplementary data file (`ucac004_supplementary_data.pdf`) is **not included** because it is a paywalled journal supplement. To replicate the evaluation:

1. Access the article via your institution: `https://doi.org/10.1093/jcr/ucac004`
2. Download the supplementary data PDF
3. Place it in this directory as `ucac004_supplementary_data.pdf`
4. Run `python scripts/evaluate.py --paper 02`

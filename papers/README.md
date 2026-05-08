# Papers Directory

This directory contains **hypotheses only** (no PDFs) from academic marketing research papers.

## Structure

```
papers/
├── training/   30 papers used to pre-load the agent's memory
│   ├── 01_Olson_2023_CommonCents/
│   │   ├── Study_1/hypotheses.txt
│   │   └── Study_2/hypotheses.txt
│   └── ...
└── test/       10 held-out papers used for evaluation only
    ├── 02_ShaniFeinstein_2022_MovingFastSlow/
    │   └── Study_1/hypotheses.txt
    └── ...
```

## hypotheses.txt Format

Each file contains the research hypotheses for one study, written in plain text:

```
H1: [Main effect] As perceived movement speed increases from slow to fast, consumers prefer
    options higher in desirability (vs. feasibility).

H2: [Moderation — construal level] ...

H3: ...
```

## Test / Training Split

The test set papers are listed in `scripts/run_batch.py` as `TEST_PAPERS`:

```python
TEST_PAPERS = {"02", "04", "08", "16", "20", "25", "33", "37", "41", "42"}
```

Run `scripts/run_batch.py` to populate memory for all **training** papers.  
Use `scripts/run_paper.py --paper papers/test/... --cross-memory` to run a test paper
with training memory injected into the pipeline.

## Adding a New Paper

1. Create a directory under `papers/training/` (or `papers/test/`) named `NN_Author_Year_ShortTitle/`
2. Create a `Study_1/` subdirectory (add `Study_2/` etc. if there are multiple studies)
3. Write `hypotheses.txt` with the hypotheses in plain text
4. Run `python scripts/run_batch.py --paper NN` to generate the memory file

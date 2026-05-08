"""
scripts/run_batch.py
Pre-loads memory/ with survey pipeline runs across training papers.
Skips TEST_PAPERS (10 papers reserved for evaluation).

After training memories exist, run a held-out test paper with cross-paper context:

  python scripts/run_batch.py --paper 02 --first-only --test-with-cross-memory

SurveyEnhancementFlow.run(..., cross_memory=True) does the same from Python;
or set env SURVEY_CROSS_MEMORY=1.

Usage:
  python scripts/run_batch.py --dry-run          # preview only
  python scripts/run_batch.py --first-only       # one study per paper (recommended)
  python scripts/run_batch.py                    # all studies
  python scripts/run_batch.py --paper 03         # one paper
  python scripts/run_batch.py --paper 03 --first-only
"""
import argparse
import os
import sys
from pathlib import Path

# Allow importing from project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

PAPERS_DIR = Path(os.getenv("PAPERS_DIR", "papers"))
MEMORY     = Path("memory")

# 10 papers reserved for testing (folder prefix numbers, zero-padded as in folder names)
TEST_PAPERS = {"02", "04", "08", "16", "20", "25", "33", "37", "41", "42"}


def make_project_name(paper_folder: str, study_folder: str) -> str:
    """e.g. '03_sharif_2022_worktounlockrewards_study_1'"""
    base  = paper_folder.lower().replace(" ", "_")
    study = study_folder.lower().replace(" ", "_")
    if study == base or study == "":
        return base
    return f"{base}_{study}"


def build_survey_input(paper_folder: str, study_folder: str, hypothesis_text: str) -> str:
    study_label = f"Study/Experiment: {study_folder}\n" if study_folder else ""
    return (
        f"Paper: {paper_folder}\n"
        f"{study_label}"
        f"Research hypotheses:\n{hypothesis_text}\n\n"
        "Task: Design a survey to test these hypotheses. "
        "Follow standard marketing research conventions "
        "(7-point Likert scales, manipulation checks, attention checks, MTurk-appropriate format)."
    )


def find_hypotheses_files(papers_dir: Path) -> list:
    """Find all hypotheses.txt files under training/ and test/ subdirs."""
    all_hyp = []
    for subdir in ("training", "test"):
        sub = papers_dir / subdir
        if sub.exists():
            all_hyp.extend(sorted(sub.rglob("hypotheses.txt")))
    # Also check root-level paper folders (no subdir)
    for hyp in sorted(papers_dir.glob("*/hypotheses.txt")):
        if hyp not in all_hyp:
            all_hyp.append(hyp)
    return sorted(all_hyp, key=lambda p: str(p))


def main(
    dry_run: bool = False,
    only_paper: str = None,
    first_only: bool = False,
    force: bool = False,
    test_with_cross_memory: bool = False,
):
    from pipeline.flow import SurveyEnhancementFlow

    all_hyp_files = find_hypotheses_files(PAPERS_DIR)

    if not all_hyp_files:
        print(f"No hypotheses.txt files found in {PAPERS_DIR}. "
              f"Set PAPERS_DIR env var or populate papers/training/ and papers/test/.")
        return

    if first_only:
        by_paper: dict = {}
        for f in all_hyp_files:
            # Determine paper root (first folder component under training/ or test/)
            parts = f.parts
            for i, part in enumerate(parts):
                if part in ("training", "test"):
                    paper = parts[i + 1] if i + 1 < len(parts) else f.parent.name
                    break
            else:
                paper = f.parts[-3] if len(f.parts) >= 3 else f.parent.name
            by_paper.setdefault(paper, []).append(f)
        all_hyp_files = [sorted(files)[0] for files in by_paper.values()]
        print(f"--first-only: reduced to {len(all_hyp_files)} studies (one per paper)\n")

    skipped, processed, failed, already_done = [], [], [], []

    for hyp_file in all_hyp_files:
        # Determine paper folder and paper number
        parts = hyp_file.parts
        paper_folder = None
        study_folder = ""
        for i, part in enumerate(parts):
            if part in ("training", "test"):
                paper_folder = parts[i + 1] if i + 1 < len(parts) else None
                # If there's another level between paper_folder and hypotheses.txt, it's a study folder
                if paper_folder and len(parts) > i + 3:
                    study_folder = parts[i + 2]
                break
        if paper_folder is None:
            paper_folder = hyp_file.parts[-3] if len(hyp_file.parts) >= 3 else hyp_file.parent.name

        paper_num = paper_folder.split("_")[0]

        if only_paper and paper_num != only_paper.zfill(2):
            continue

        if paper_num in TEST_PAPERS and not (test_with_cross_memory and only_paper):
            skipped.append(paper_folder)
            continue

        project_name  = make_project_name(paper_folder, study_folder)
        memory_exists = list(MEMORY.glob(f"{project_name}_*.json"))
        if memory_exists and not force:
            already_done.append(project_name)
            continue
        if memory_exists and force:
            for old in memory_exists:
                old.unlink()
            print(f"  [FORCE] Deleted old memory for {project_name}")

        hypothesis_text = hyp_file.read_text(encoding="utf-8", errors="ignore").strip()
        if not hypothesis_text:
            print(f"  [SKIP] Empty hypotheses.txt: {hyp_file}")
            continue

        survey_input = build_survey_input(paper_folder, study_folder, hypothesis_text)

        if dry_run:
            print(f"  [DRY RUN] {project_name}")
            processed.append(project_name)
            continue

        print(f"\nProcessing: {project_name}")
        try:
            flow = SurveyEnhancementFlow()
            flow.run(
                survey_input,
                project_name=project_name,
                cross_memory=bool(test_with_cross_memory and paper_num in TEST_PAPERS),
            )
            processed.append(project_name)
            print(f"  Done: {project_name}")
        except Exception as e:
            print(f"  FAILED {project_name}: {e}")
            failed.append(project_name)

    print(f"\n{'='*60}")
    print(f"Processed : {len(processed)}")
    print(f"Skipped   : {len(skipped)} (test set papers: {sorted(set(skipped))})")
    print(f"Already   : {len(already_done)} (memory already exists)")
    print(f"Failed    : {len(failed)}")
    if failed:
        print("  Failed projects:", failed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch memory loader for training papers")
    parser.add_argument("--dry-run",    action="store_true", help="Preview without running pipeline")
    parser.add_argument("--first-only", action="store_true",
                        help="Process only the first study per paper (recommended for initial memory load)")
    parser.add_argument("--paper",      type=str, default=None,
                        help="Process only this paper number (e.g. --paper 03)")
    parser.add_argument("--force",      action="store_true",
                        help="Delete and re-run papers that already have memory files")
    parser.add_argument(
        "--test-with-cross-memory",
        action="store_true",
        help="With --paper, allow a TEST_PAPERS id and run with cross_memory=True "
             "(inject other papers' memory summaries at Step 2). Requires existing training sessions in memory/.",
    )
    args = parser.parse_args()
    if args.test_with_cross_memory and not args.paper:
        parser.error("--test-with-cross-memory requires --paper <id>")
    main(
        dry_run=args.dry_run,
        only_paper=args.paper,
        first_only=args.first_only,
        force=args.force,
        test_with_cross_memory=args.test_with_cross_memory,
    )

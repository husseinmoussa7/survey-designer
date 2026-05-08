"""
scripts/run_paper.py
Runs the full agent pipeline (parallel enhancement + critic + memory) on a single paper
from the papers/ directory, then prints instructions to run evaluation.

Usage:
  python scripts/run_paper.py --paper papers/test/02_ShaniFeinstein_2022_MovingFastSlow/Study_1
  python scripts/run_paper.py --paper papers/training/01_Olson_2023_CommonCents/Study_1
  python scripts/run_paper.py --paper papers/test/02_ShaniFeinstein_2022_MovingFastSlow/Study_1 --cross-memory
"""
import argparse
import json
import os
import sys
from pathlib import Path

# Allow importing from project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()


def make_project_name(paper_path: Path) -> str:
    """Derive project name from path, e.g. '02_shanifeinstein_2022_movingfastslow_study_1'."""
    parts = paper_path.parts
    # Find the paper folder (one below training/ or test/)
    for i, part in enumerate(parts):
        if part in ("training", "test"):
            paper_folder = parts[i + 1] if i + 1 < len(parts) else paper_path.name
            study_folder = parts[i + 2] if i + 2 < len(parts) else ""
            base  = paper_folder.lower().replace(" ", "_")
            study = study_folder.lower().replace(" ", "_")
            return f"{base}_{study}" if study and study != base else base
    # Fallback
    return paper_path.name.lower().replace(" ", "_")


def build_survey_input(paper_path: Path, hypothesis_text: str) -> str:
    parts = paper_path.parts
    paper_folder = paper_path.name
    study_label  = ""
    for i, part in enumerate(parts):
        if part in ("training", "test"):
            paper_folder = parts[i + 1] if i + 1 < len(parts) else paper_path.name
            if i + 2 < len(parts):
                study_label = f"Study/Experiment: {parts[i + 2]}\n"
            break
    return (
        f"Paper: {paper_folder}\n"
        f"{study_label}"
        f"Research hypotheses:\n{hypothesis_text}\n\n"
        "Task: Design a survey to test these hypotheses. "
        "Follow standard marketing research conventions "
        "(7-point Likert scales, manipulation checks, attention checks, MTurk-appropriate format)."
    )


def main():
    parser = argparse.ArgumentParser(description="Run the full survey pipeline on a single paper")
    parser.add_argument("--paper", required=True,
                        help="Path to paper directory containing hypotheses.txt "
                             "(e.g. papers/test/02_ShaniFeinstein_2022_MovingFastSlow/Study_1)")
    parser.add_argument("--cross-memory", action="store_true",
                        help="Inject training memory summaries into Step 2 (useful for test papers)")
    parser.add_argument("--output-dir", default=None,
                        help="Directory to save ai_survey.json and critique.json (default: results/<project_name>)")
    args = parser.parse_args()

    paper_path = Path(args.paper)
    hyp_file   = paper_path / "hypotheses.txt"

    if not hyp_file.exists():
        # Try to find hypotheses.txt anywhere in the directory
        found = list(paper_path.rglob("hypotheses.txt"))
        if not found:
            print(f"Error: no hypotheses.txt found under {paper_path}")
            sys.exit(1)
        hyp_file = found[0]

    hypothesis_text = hyp_file.read_text(encoding="utf-8", errors="ignore").strip()
    if not hypothesis_text:
        print(f"Error: hypotheses.txt is empty: {hyp_file}")
        sys.exit(1)

    project_name = make_project_name(paper_path)
    survey_input = build_survey_input(paper_path, hypothesis_text)

    output_dir = Path(args.output_dir) if args.output_dir else Path("results") / project_name
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(f"STEP 1: Loading hypothesis from {hyp_file}")
    print("=" * 60)
    print(hypothesis_text)
    print(f"\nProject name: {project_name}")
    print(f"Output dir:   {output_dir}")

    print("\n" + "=" * 60)
    print("STEP 2: Running agent pipeline (parallel + critic + memory)")
    print("=" * 60)

    from pipeline.flow import SurveyEnhancementFlow

    flow   = SurveyEnhancementFlow()
    result = flow.run(survey_input, project_name=project_name, cross_memory=args.cross_memory)

    ai_survey_path = output_dir / "ai_survey.json"
    ai_survey_path.write_text(json.dumps(result, indent=2))
    print(f"\nAI survey saved to: {ai_survey_path}")

    critique_path = output_dir / "critique.json"
    critique_path.write_text(json.dumps(flow.critique_result, indent=2))
    print(f"Critique saved to: {critique_path}")

    print(f"\nPipeline complete. To evaluate, run:")
    print(f"  python scripts/evaluate.py --paper {project_name}")


if __name__ == "__main__":
    main()

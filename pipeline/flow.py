# pipeline/flow.py
# Version 6: Critic agent, persistent memory, parallel discussions, cross-paper training memory.
import os
import yaml
import json
import warnings
import asyncio
import tempfile
import shutil
import copy
import logging
import concurrent.futures
from collections import defaultdict
from pathlib import Path
from datetime import datetime
from typing import Literal, Dict, List, Any, Union, Optional
from pydantic import BaseModel, ValidationError, Field, field_validator
from crewai import Agent, Task, Crew, Process
from crewai.tasks.task_output import OutputFormat

# Simulation and debiasing are optional downstream modules not included in this project.
run_all_survey_responses_json = None
openai_llm = None
run_debias_pipeline = None

from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

import certifi
import openai
import requests
import zipfile
import io
import time
import pandas as pd
import boto3
from dotenv import load_dotenv
import re
from dotenv import load_dotenv
load_dotenv()
import xml.etree.ElementTree as ET

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MEMORY_SESSION_FILE_RE = re.compile(r"^(.+)_(\d{8})_(\d{6})\.json$")


def _test_paper_ids_for_memory_filter():
    """IDs (zero-padded) reserved as held-out test papers — exclude from training-only cross-memory."""
    try:
        from scripts.run_batch import TEST_PAPERS
        return frozenset(TEST_PAPERS)
    except ImportError:
        try:
            from run_batch import TEST_PAPERS
            return frozenset(TEST_PAPERS)
        except ImportError:
            return frozenset()


# ========== Pydantic Models ==========
class Question(BaseModel):
    question_id: str
    question_text: str
    input_type: Literal["multiple_choice", "single_choice", "slider", "text_input", "scale", "checkbox"]
    input_config: Dict[str, Any]

class Survey(BaseModel):
    theme: str
    purpose: str
    questions: List[Question]

# ========== Helper Function for Parsing AI Output ==========
def _parse_and_clean_json(raw_output: str) -> dict:
    """Cleans markdown fences and parses a JSON string from AI output."""
    if not isinstance(raw_output, str):
        if isinstance(raw_output, dict):
            return raw_output
        raise TypeError(f"Expected string for parsing, but got {type(raw_output)}")

    cleaned_output = raw_output.strip()
    if cleaned_output.startswith("```json"):
        cleaned_output = cleaned_output.split("```json", 1)[1]
    elif cleaned_output.startswith("```"):
        cleaned_output = cleaned_output.split("```", 1)[1]

    if "```" in cleaned_output:
        cleaned_output = cleaned_output.rsplit("```", 1)[0]

    cleaned_output = cleaned_output.strip()

    try:
        return json.loads(cleaned_output)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse cleaned JSON output: {e}\\nCleaned output attempt:\\n{cleaned_output}")


# ========== Interactive Survey Enhancement Flow ==========
class SurveyEnhancementFlow:
    """Interactive flow for enhancing surveys with user feedback"""

    MEMORY_DIR = Path("memory")
    CHECKPOINT_SUFFIX = "_checkpoint.json"

    def __init__(self):
        self.convert_agent, self.editor_agent, self.enhancement_agent, self.critic_agent = self._load_agents()
        self.survey_dict = None
        self.enhanced_dict = None
        self.parallel_runs = []
        self.checkpoints   = {}
        self.critique_result = None
        self.MEMORY_DIR.mkdir(exist_ok=True)

    def _load_agents(self):
        convert_agent = Agent(
            role='Raw Text to JSON Survey Converter',
            goal='Accurately convert raw text containing a survey topic and questions into a structured JSON format. Focus ONLY on conversion, not on improving the content.',
            backstory='You are a precision-focused data entry bot. Your sole purpose is to parse text and structure it into a clean, basic JSON format without altering the content of the questions or topic.',
            verbose=True,
            allow_delegation=False
        )

        editor_agent = Agent(
            role='Academic Survey Editor',
            goal='Critique and enhance a given JSON survey for clarity, neutrality, and academic rigor. You ONLY modify the provided JSON; you DO NOT create new surveys.',
            backstory='You are an experienced research methodologist. You receive pre-formatted JSON surveys and your job is to refine them, providing clear justifications for every change.',
            verbose=True,
            allow_delegation=False
        )

        enhancement_agent = Agent(
            name="Survey Enhancement Agent",
            role="Survey Enhancement Agent",
            goal="To improve survey design by incorporating user feedback in an iterative process",
            backstory="I am an AI assistant specialized in survey design and enhancement. I work iteratively with users to refine surveys until they perfectly match the user's needs and standards.",
            verbose=True,
            allow_delegation=False
        )

        critic_agent = Agent(
            role="Survey Methodologist Critic",
            goal="Identify flaws, biases, and validity threats in survey instruments before deployment. Do not rewrite — critique only.",
            backstory=(
                "You are a rigorous survey methodologist trained to find problems others miss. "
                "You scrutinize every question for leading language, double-barreled structure, "
                "social desirability bias, ambiguous wording, and scale mismatches. You have "
                "reviewed hundreds of surveys for top marketing and operations management journals. "
                "You do not validate — you challenge."
            ),
            verbose=True,
            allow_delegation=False
        )

        return convert_agent, editor_agent, enhancement_agent, critic_agent

    # ── Persistent memory methods ─────────────────────────────────────────────

    def save_session(self, project_name: str):
        """Save full session to disk including parallel runs and checkpoints."""
        session = {
            "timestamp":      datetime.now().isoformat(),
            "project":        project_name,
            "survey_v0":      self.survey_dict,
            "survey_v1":      self.enhanced_dict,
            "critique":       getattr(self, "critique_result", None),
            "discussion_log": getattr(self, "discussion_log", []),
            "parallel_runs":  self.parallel_runs,
            "checkpoints":    self.checkpoints,
        }
        path = self.MEMORY_DIR / f"{project_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path.write_text(json.dumps(session, indent=2))
        logger.info(f"Session saved to {path}")
        return str(path)

    def _write_checkpoint(self, project_name: str, step: str, data: dict):
        self.checkpoints[step] = {"timestamp": datetime.now().isoformat(), "data": data}
        cp_path = self.MEMORY_DIR / f"{project_name}{self.CHECKPOINT_SUFFIX}"
        cp_path.write_text(json.dumps({
            "project":     project_name,
            "last_step":   step,
            "checkpoints": self.checkpoints,
        }, indent=2))

    def _load_checkpoint(self, project_name: str) -> dict:
        cp_path = self.MEMORY_DIR / f"{project_name}{self.CHECKPOINT_SUFFIX}"
        if cp_path.exists():
            try:
                data = json.loads(cp_path.read_text())
                logger.info(f"Checkpoint found for '{project_name}': last completed step = {data.get('last_step')}")
                return data
            except Exception:
                pass
        return {}

    def _clear_checkpoint(self, project_name: str):
        cp_path = self.MEMORY_DIR / f"{project_name}{self.CHECKPOINT_SUFFIX}"
        if cp_path.exists():
            cp_path.unlink()

    def _summarize_saved_session(self, data: dict, heading: str) -> str:
        """One memory JSON → human-readable block (shared by same-paper and cross-paper loaders)."""
        ts = (data.get("timestamp") or "")[:16]
        v1_qs = (data.get("survey_v1") or {}).get("revised_survey", {}).get("questions", [])
        n_q = len(v1_qs)

        crit_lines = []
        if data.get("critique"):
            crit = data["critique"] if isinstance(data["critique"], dict) else {}
            for entry in crit.get("question_critiques", [])[:5]:
                if not isinstance(entry, dict):
                    continue
                qid    = entry.get("question_id", "?")
                issues = entry.get("issues", [])
                if isinstance(issues, dict):
                    issues = [issues]
                elif not isinstance(issues, list):
                    issues = []
                if not issues and any(k in entry for k in ("leading_language","double_barreled","ambiguous_wording")):
                    issues = [{"type": k, "severity": entry[k]}
                              for k in ("leading_language","double_barreled","ambiguous_wording","scale_appropriateness")
                              if isinstance(entry.get(k), int) and entry[k] > 0]
                for iss in issues[:2]:
                    if not isinstance(iss, dict):
                        continue
                    crit_lines.append(
                        f"  [{qid}] sev{iss.get('severity','?')} {iss.get('type','')}: {iss.get('explanation','')[:80]}"
                    )
            for sl in crit.get("survey_level_issues", [])[:3]:
                if isinstance(sl, dict):
                    crit_lines.append(f"  [survey] {sl.get('type','')}: {sl.get('explanation','')[:80]}")

        q_topics = [q.get("question_text","")[:60] for q in v1_qs[:4]]

        return (
            f"[{heading} {ts}] {n_q} questions.\n"
            + (f"  Key questions: {'; '.join(q_topics)}\n" if q_topics else "")
            + (f"  Critic issues:\n" + "\n".join(crit_lines) if crit_lines else "  No critique recorded.")
        )

    def load_prior_sessions(self, project_name: str) -> str:
        """Load rich prior-session context — actual issues and fixes from previous runs."""
        files = sorted(f for f in self.MEMORY_DIR.glob(f"{project_name}_*.json")
                       if self.CHECKPOINT_SUFFIX not in f.name)
        if not files:
            return ""
        summaries = []
        for f in files[-3:]:
            data = json.loads(f.read_text())
            summaries.append(self._summarize_saved_session(data, "Prior run"))
        context = "\n\n".join(summaries)
        logger.info(f"Loaded {len(files)} prior session(s) for '{project_name}'")
        return context

    @staticmethod
    def _paper_num_from_project_stem(stem: str) -> Optional[str]:
        """Leading 'NN_' or 'N_' in project folder style → 'NN' for test/train filtering."""
        first = stem.split("_", 1)[0]
        if first.isdigit():
            return first.zfill(2) if len(first) <= 2 else first
        return None

    def load_cross_paper_training_context(
        self,
        project_name: str,
        max_papers: int = 20,
        training_pool_only: bool = True,
    ) -> str:
        """
        Load summarized critique/outcomes from other saved sessions in memory/ so a new
        paper (e.g. held-out test) can benefit from batch-ran training papers.

        Skips the current project_name (no self-leakage). If training_pool_only, skips
        memories whose paper ID is in TEST_PAPERS from scripts/run_batch.py.
        """
        test_ids = _test_paper_ids_for_memory_filter() if training_pool_only else frozenset()

        stem_files: Dict[str, List[Path]] = defaultdict(list)
        for f in self.MEMORY_DIR.iterdir():
            if not f.is_file() or f.suffix != ".json":
                continue
            if self.CHECKPOINT_SUFFIX in f.name:
                continue
            m = MEMORY_SESSION_FILE_RE.match(f.name)
            if not m:
                continue
            stem = m.group(1)
            if stem == project_name:
                continue
            pid = self._paper_num_from_project_stem(stem)
            if pid is not None and pid in test_ids:
                continue
            stem_files[stem].append(f)

        if not stem_files:
            logger.info("Cross-paper training memory: no eligible session files found")
            return ""

        picks: List[tuple] = []
        for stem, paths in stem_files.items():
            best = max(paths, key=lambda p: p.name)
            picks.append((stem, best))
        picks.sort(key=lambda x: x[0])
        picks = picks[:max_papers]

        summaries = []
        for stem, path in picks:
            try:
                data = json.loads(path.read_text())
            except Exception as e:
                logger.warning("Skip unreadable memory %s: %s", path, e)
                continue
            summaries.append(self._summarize_saved_session(data, f"Other paper: {stem}"))

        ctx = "\n\n".join(summaries)
        logger.info(
            "Cross-paper training memory: %d example paper(s) (cap=%d, training_only=%s)",
            len(summaries), max_papers, training_pool_only,
        )
        return ctx

    # ── Parallel enhancement + scored merge ───────────────────────────────────
    def run_parallel_enhancement(self, survey_json: dict, n_runs: int = 3) -> dict:
        """
        Run the editor agent n_runs times in parallel.
        Score each run before merging so bad generations are filtered out.
        Store all raw outputs on self.parallel_runs for saving and inspection.
        """
        survey_str = json.dumps(survey_json, indent=2)

        def single_run(seed):
            task = Task(
                description=(
                    f"You are an expert survey methodologist (run variant {seed}). "
                    f"Critique and improve the following JSON survey.\n"
                    f"DO NOT change the fundamental topic. Improve wording, response options, and academic rigor.\n\n"
                    f"JSON Survey:\n---\n{survey_str}\n---\n\n"
                    f"Output a single JSON with 'original_with_comments' and 'revised_survey' keys."
                ),
                agent=self.editor_agent,
                expected_output="A JSON object with 'original_with_comments' and 'revised_survey' keys."
            )
            crew = Crew(agents=[self.editor_agent], tasks=[task], process=Process.sequential)
            return crew.kickoff().raw

        logger.info(f"Running {n_runs} parallel enhancement runs...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=n_runs) as executor:
            raw_results = list(executor.map(single_run, range(1, n_runs + 1)))

        def score_run(raw: str) -> tuple:
            try:
                parsed = _parse_and_clean_json(raw)
                rs = parsed.get("revised_survey", {})
                qs = rs.get("questions", [])
                if not qs:
                    return -1, parsed, raw
                n_q     = len(qs)
                types   = len(set(q.get("input_type","") for q in qs))
                has_mc  = any(q.get("input_type","") in ("multiple_choice","single_choice") for q in qs)
                has_sc  = any(q.get("input_type","") in ("scale","likert") for q in qs)
                score   = n_q + types * 2 + (2 if has_mc else 0) + (2 if has_sc else 0)
                return score, parsed, raw
            except Exception:
                return -1, {}, raw

        scored = sorted([score_run(r) for r in raw_results], key=lambda x: x[0], reverse=True)

        self.parallel_runs = [
            {"run": i+1, "score": s, "output": raw}
            for i, (s, _, raw) in enumerate(scored)
        ]
        print(f"  Parallel run scores: {[s for s,_,_ in scored]}")

        valid = [(s, parsed, raw) for s, parsed, raw in scored if s > 0]
        if not valid:
            raise ValueError("All parallel enhancement runs failed to produce valid output.")
        if len(valid) == 1:
            return valid[0][1]

        run_summaries = []
        for i, (score, parsed, raw) in enumerate(valid):
            qs = parsed.get("revised_survey", {}).get("questions", [])
            q_texts = [f"  Q{j+1}: {q.get('question_text','')[:80]}" for j, q in enumerate(qs[:6])]
            comments = str(parsed.get("original_with_comments", ""))[:300]
            run_summaries.append(
                f"Run {i+1} (quality score={score}, {len(qs)} questions):\n"
                f"  Key changes noted: {comments}\n"
                f"  Questions:\n" + "\n".join(q_texts)
            )

        merge_task = Task(
            description=(
                "You have received summaries of multiple enhanced survey versions from parallel runs. "
                "Synthesize the best improvements from each version into a single final survey. "
                "For each question in your output, note which run it came from and why it was chosen.\n\n"
                + "\n\n".join(run_summaries)
                + f"\n\nOriginal survey for reference:\n{survey_str}\n\n"
                "Output a single JSON with 'original_with_comments' (explaining choices per run) "
                "and 'revised_survey' keys."
            ),
            agent=self.editor_agent,
            expected_output="A single merged JSON with 'original_with_comments' and 'revised_survey' keys."
        )
        merge_crew = Crew(agents=[self.editor_agent], tasks=[merge_task], process=Process.sequential)
        merged_raw = merge_crew.kickoff().raw
        return _parse_and_clean_json(merged_raw)

    # ── Meeting function: multi-agent debate round ─────────────────────────────
    def run_meeting_discussion(self, survey_json: dict, n_rounds: int = 2) -> dict:
        """
        Run n_rounds of critic → editor revision before the formal critic pass.
        Each round: critic posts concerns → editor revises.
        Stores discussion_log on self for saving to memory.
        """
        current_survey = survey_json
        discussion_log = []

        for round_num in range(1, n_rounds + 1):
            print(f"\n  [Meeting Round {round_num}/{n_rounds}] Critic reviewing...")
            survey_str = json.dumps(
                current_survey.get("revised_survey", current_survey), indent=2
            )

            critic_task = Task(
                description=(
                    f"[Meeting Round {round_num} — Critic] Review this survey and list your top "
                    f"concerns as a numbered list. Be specific about which question has each problem "
                    f"and why. Focus on wording, bias, scale issues, and survey structure. "
                    f"Do NOT rewrite the survey — only raise concerns.\n\nSurvey:\n{survey_str}"
                ),
                agent=self.critic_agent,
                expected_output="A numbered list of survey methodology concerns."
            )
            critic_crew = Crew(
                agents=[self.critic_agent], tasks=[critic_task], process=Process.sequential
            )
            critic_feedback = critic_crew.kickoff().raw
            discussion_log.append(
                {"round": round_num, "role": "critic", "content": critic_feedback}
            )

            print(f"  [Meeting Round {round_num}/{n_rounds}] Editor revising...")

            editor_task = Task(
                description=(
                    f"[Meeting Round {round_num} — Editor] The survey methodologist critic raised "
                    f"concerns about this survey. Revise the survey to address them.\n\n"
                    f"Critic concerns:\n{critic_feedback}\n\n"
                    f"Current survey:\n{survey_str}\n\n"
                    f"Return a JSON object with 'revised_survey' and 'explanations' keys."
                ),
                agent=self.enhancement_agent,
                expected_output="JSON with 'revised_survey' and 'explanations' keys.",
                output_format=OutputFormat.JSON
            )
            editor_crew = Crew(
                agents=[self.enhancement_agent], tasks=[editor_task], process=Process.sequential
            )
            editor_raw = editor_crew.kickoff().raw
            try:
                revised = _parse_and_clean_json(editor_raw)
                if "revised_survey" in revised and "questions" in revised["revised_survey"]:
                    prev_qs = {q["question_id"]: q["question_text"]
                               for q in current_survey.get("revised_survey", current_survey).get("questions", [])}
                    new_qs  = {q["question_id"]: q["question_text"]
                               for q in revised["revised_survey"]["questions"]}
                    diff_lines = []
                    for qid, new_text in new_qs.items():
                        if qid not in prev_qs:
                            diff_lines.append(f"+ ADDED [{qid}]: {new_text}")
                        elif prev_qs[qid] != new_text:
                            diff_lines.append(f"~ REWORDED [{qid}]:\n  Before: {prev_qs[qid]}\n  After:  {new_text}")
                    for qid in prev_qs:
                        if qid not in new_qs:
                            diff_lines.append(f"- REMOVED [{qid}]")
                    explanations = revised.get("explanations", {})
                    if explanations:
                        diff_lines.append("\nExplanations from editor:")
                        for k, v in explanations.items():
                            diff_lines.append(f"  [{k}]: {v}")
                    editor_summary = "\n".join(diff_lines) if diff_lines else "No changes made."
                    current_survey = revised
                    discussion_log.append(
                        {"round": round_num, "role": "editor", "content": editor_summary}
                    )
                    print(f"  [Meeting Round {round_num}/{n_rounds}] Done. ({len(diff_lines)} changes)")
            except Exception as e:
                print(f"  [Meeting Round {round_num}] Warning: editor revision failed: {e}")

        self.discussion_log = discussion_log
        return current_survey

    def run(
        self,
        survey_text,
        project_name: str = "default",
        cross_memory: bool = False,
        cross_memory_max_papers: int = 20,
        cross_memory_training_only: bool = True,
    ):
        """
        Run the full survey enhancement pipeline.

        Steps:
          1. Convert raw text → JSON
          2. Parallel enhancement (3 runs) + scored merge
          2.5. Meeting discussion (critic → editor, 2 rounds)
          3. Formal critic review
          4a/4b/4c. Severity-driven revision passes (3 → 2 → 1)

        cross_memory: inject summaries from other papers' saved sessions (training set)
                      into Step 2. Env var SURVEY_CROSS_MEMORY=1 also enables this.
        """
        checkpoint = self._load_checkpoint(project_name)
        if checkpoint:
            last_step = checkpoint.get("last_step", "")
            print(f"\n--- Resuming from checkpoint: last completed step = '{last_step}' ---")
            saved_cps = checkpoint.get("checkpoints", {})
            self.checkpoints = saved_cps
            if "step1" in saved_cps:
                initial_survey_json = saved_cps["step1"]["data"]
                self.survey_dict = initial_survey_json
            if "step2_merged" in saved_cps:
                self.survey_dict = saved_cps["step2_merged"]["data"]
                self.enhanced_dict = self.survey_dict
            if "step2_5_meeting" in saved_cps:
                self.enhanced_dict = saved_cps["step2_5_meeting"]["data"]
                self.discussion_log = saved_cps["step2_5_meeting"].get("discussion_log", [])
            if "step3_critique" in saved_cps:
                self.critique_result = saved_cps["step3_critique"]["data"]

        prior_same = self.load_prior_sessions(project_name)
        env_cross = os.environ.get("SURVEY_CROSS_MEMORY", "").strip().lower() in ("1", "true", "yes")
        use_cross = cross_memory or env_cross
        try:
            max_cm = int(os.environ.get("SURVEY_CROSS_MEMORY_MAX", str(cross_memory_max_papers)))
        except ValueError:
            max_cm = cross_memory_max_papers
        train_only_env = os.environ.get("SURVEY_CROSS_MEMORY_TRAINING_ONLY", "").strip().lower()
        if train_only_env in ("0", "false", "no"):
            train_only = False
        elif train_only_env in ("1", "true", "yes"):
            train_only = True
        else:
            train_only = cross_memory_training_only

        prior_parts = []
        if prior_same:
            prior_parts.append("=== Prior runs on THIS paper (same project) ===\n" + prior_same)
        if use_cross:
            train_ctx = self.load_cross_paper_training_context(
                project_name, max_papers=max_cm, training_pool_only=train_only
            )
            if train_ctx:
                prior_parts.append(
                    "=== Other papers (training memory — apply lessons, do not copy wording/topics) ===\n"
                    + train_ctx
                )
        prior_context = "\n\n".join(prior_parts)
        if prior_context:
            print(f"\n--- Loaded session / cross-paper memory for '{project_name}' ---")
            print(prior_context)

        print("--- Step 1: Converting Raw Text to Structured JSON ---")

        convert_task_description = f"""
        Parse the following raw survey text and convert it into a simple JSON object.
        The JSON object must have a "theme" key and a "questions" key.
        Each question in the "questions" array should have a "question_id", "question_text", "input_type", and "input_config".
        - For question type, make a best guess (e.g., 'text_input', 'multiple_choice', 'slider', 'scale').
        - Do NOT invent new questions or change the wording. Your only job is to structure the provided text.

        Raw Text to Convert:
        ---
        {survey_text}
        ---

        Required JSON Output format:
        ```json
        {{
            "theme": "The topic from the raw text",
            "purpose": "A brief purpose based on the topic",
            "questions": [
                {{
                    "question_id": "q1",
                    "question_text": "The first question from the text",
                    "input_type": "text_input",
                    "input_config": {{}}
                }},
                {{
                    "question_id": "q2",
                    "question_text": "The second question from the text",
                    "input_type": "multiple_choice",
                    "input_config": {{"options": ["Option A", "Option B"]}}
                }}
            ]
        }}
        ```
        """
        convert_task = Task(
            description=convert_task_description,
            agent=self.convert_agent,
            expected_output="A single, clean JSON object representing the structured version of the raw text."
        )

        conversion_crew = Crew(agents=[self.convert_agent], tasks=[convert_task], process=Process.sequential)
        conversion_result = conversion_crew.kickoff()

        try:
            raw_text_output = conversion_result.raw
            initial_survey_json = _parse_and_clean_json(raw_text_output)

            if 'questions' not in initial_survey_json or not initial_survey_json['questions']:
                raise ValueError("Initial conversion failed to produce a valid questions array.")
            print("--- Step 1 SUCCESS: Successfully converted text to JSON. ---")
            print(json.dumps(initial_survey_json, indent=2))
            self._write_checkpoint(project_name, "step1", initial_survey_json)

        except (ValueError, TypeError) as e:
            raise ValueError(f"Step 1 (Conversion) failed: {e}. Raw output from converter agent: {getattr(conversion_result, 'raw', conversion_result)}")

        print("\n--- Step 2: Parallel Enhancement (3 runs) + Merge ---")
        prior_note = f"\n\nNote from prior sessions:\n{prior_context}" if prior_context else ""

        survey_with_context = dict(initial_survey_json)
        if prior_context:
            survey_with_context["_prior_session_context"] = prior_context

        try:
            final_survey_json = self.run_parallel_enhancement(survey_with_context, n_runs=3)
            final_survey_json.get("revised_survey", {}).pop("_prior_session_context", None)

            if 'revised_survey' not in final_survey_json or 'questions' not in final_survey_json['revised_survey']:
                raise ValueError("Parallel enhancement failed to produce a valid 'revised_survey' object.")
            print("--- Step 2 SUCCESS: Parallel enhancement complete. ---")
            self.survey_dict = final_survey_json
            self.enhanced_dict = self.survey_dict
            self._write_checkpoint(project_name, "step2_merged", final_survey_json)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Step 2 (Parallel Enhancement) failed: {e}")

        print("\n--- Step 2.5: Meeting Discussion (2 rounds) ---")
        self.enhanced_dict = self.run_meeting_discussion(self.enhanced_dict, n_rounds=2)
        print("--- Step 2.5 SUCCESS: Meeting discussion complete. ---")
        self._write_checkpoint(project_name, "step2_5_meeting", {
            **self.enhanced_dict,
            "discussion_log": getattr(self, "discussion_log", []),
        })

        print("\n--- Step 3: Critic Review ---")
        revised_str = json.dumps(self.enhanced_dict.get("revised_survey", self.enhanced_dict), indent=2)

        meeting_context = ""
        disc = getattr(self, "discussion_log", [])
        if disc:
            critic_concerns = [e["content"] for e in disc if e.get("role") == "critic"]
            meeting_context = (
                "\n\nNote: This survey has already gone through a meeting discussion. "
                "The following concerns were raised (do not repeat them unless still unresolved):\n"
                + (f"Survey methodologist raised: {'; '.join(c[:120] for c in critic_concerns[:2])}\n" if critic_concerns else "")
            )

        critique_task = Task(
            description=(
                f"Review the following survey for methodological flaws.\n"
                f"For each question assess: (1) leading language, (2) double-barreled structure, "
                f"(3) social desirability bias, (4) ambiguous wording, (5) scale appropriateness.\n"
                f"At the survey level, flag missing constructs, redundant items, and theoretical gaps.\n"
                f"Severity: 1=minor, 2=moderate, 3=must fix before deployment.\n"
                f"{meeting_context}\n\n"
                f"Survey:\n---\n{revised_str}\n---\n\n"
                f"Return a JSON object with 'question_critiques' and 'survey_level_issues' keys."
            ),
            agent=self.critic_agent,
            expected_output="JSON with 'question_critiques' list and 'survey_level_issues' list."
        )
        critique_crew = Crew(agents=[self.critic_agent], tasks=[critique_task], process=Process.sequential)
        critique_raw = critique_crew.kickoff().raw
        try:
            self.critique_result = _parse_and_clean_json(critique_raw)
            n_q_issues = len(self.critique_result.get("question_critiques", []))
            n_s_issues = len(self.critique_result.get("survey_level_issues", []))
            print(f"--- Step 3 SUCCESS: Critic found {n_q_issues} question issue(s) and {n_s_issues} survey-level issue(s). ---")
            self._write_checkpoint(project_name, "step3_critique", self.critique_result)
        except (ValueError, TypeError):
            self.critique_result = {"raw": critique_raw}
            print("--- Step 3: Critic response could not be parsed as JSON. Stored raw. ---")

        severity_3_q = [i for i in self.critique_result.get("question_critiques", []) if i.get("severity") == 3]
        severity_3_s = [i for i in self.critique_result.get("survey_level_issues", []) if i.get("severity") == 3]
        severity_3 = severity_3_q + severity_3_s
        if severity_3:
            print(f"\n--- Step 4a: Addressing {len(severity_3)} critical issue(s) ---")
            self.run_single_enhancement_cycle(
                user_feedback=f"The following critical issues MUST be fixed before deployment:\n{json.dumps(severity_3, indent=2)}"
            )
            self._write_checkpoint(project_name, "step4a", self.enhanced_dict)
        else:
            print("\n--- Step 4a: No severity-3 issues. Skipping. ---")

        severity_2_q = [i for i in self.critique_result.get("question_critiques", []) if i.get("severity") == 2]
        severity_2_s = [i for i in self.critique_result.get("survey_level_issues", []) if i.get("severity") == 2]
        severity_2 = severity_2_q + severity_2_s
        if severity_2:
            print(f"\n--- Step 4b: Fixing {len(severity_2)} moderate issue(s) ---")
            self.run_single_enhancement_cycle(
                user_feedback=(
                    "Fix the following MODERATE wording issues in existing questions. "
                    "Do NOT add new questions or change the overall structure. "
                    "Only reword, clarify, or adjust scales where flagged:\n"
                    + json.dumps(severity_2, indent=2)
                )
            )
            self._write_checkpoint(project_name, "step4b", self.enhanced_dict)
        else:
            print("\n--- Step 4b: No severity-2 issues. Skipping. ---")

        severity_1_q = [i for i in self.critique_result.get("question_critiques", []) if i.get("severity") == 1]
        severity_1_s = [i for i in self.critique_result.get("survey_level_issues", []) if i.get("severity") == 1]
        severity_1 = severity_1_q + severity_1_s
        if severity_1:
            print(f"\n--- Step 4c: Polishing {len(severity_1)} minor issue(s) ---")
            self.run_single_enhancement_cycle(
                user_feedback=(
                    "Make minimal polish-only changes for the following MINOR issues. "
                    "Do NOT add questions, restructure, or change anything not flagged:\n"
                    + json.dumps(severity_1, indent=2)
                )
            )
            self._write_checkpoint(project_name, "step4c", self.enhanced_dict)
        else:
            print("\n--- Step 4c: No severity-1 issues. Skipping. ---")

        saved_path = self.save_session(project_name)
        self._clear_checkpoint(project_name)
        print(f"\n--- Session saved to: {saved_path} ---")

        return self.enhanced_dict

    def run_single_enhancement_cycle(self, user_feedback):
        """Runs one cycle of AI enhancement based on user feedback."""
        if not self.enhanced_dict:
            raise ValueError("No survey has been processed yet.")

        survey_json_to_enhance = json.dumps(self.enhanced_dict.get('revised_survey', self.enhanced_dict), indent=2)

        meeting_context_block = ""
        disc = getattr(self, "discussion_log", [])
        if disc:
            lines = []
            for e in disc:
                role    = e.get("role","?").title()
                content = str(e.get("content",""))[:200]
                lines.append(f"  [{role} Rd{e.get('round','?')}]: {content}")
            meeting_context_block = (
                "\n--- PRIOR MEETING DISCUSSION (for context — do not repeat fixes already made) ---\n"
                + "\n".join(lines) + "\n"
            )

        enhanced_task_description = f"""
        You are a survey design expert. Your task is to revise the JSON survey provided below based on the user's feedback.
        **CRITICAL INSTRUCTIONS:**
        1.  You MUST modify the EXACT JSON survey provided in the "SURVEY TO MODIFY" section.
        2.  DO NOT generate a new survey from scratch.
        3.  Apply the user's feedback to improve the questions, options, or structure.
        4.  Your response MUST be a single JSON object with two keys: 'revised_survey' and 'explanations'.
        --- SURVEY TO MODIFY ---
        ```json
        {survey_json_to_enhance}
        ```
        --- USER FEEDBACK ---
        {user_feedback}
        {meeting_context_block}--- REQUIRED OUTPUT FORMAT ---
        ```json
        {{
            "revised_survey": {{ ... }},
            "explanations": {{ ... }}
        }}
        ```
        """

        enhancement_task = Task(
            name="enhance_survey_iteratively",
            description=enhanced_task_description,
            agent=self.enhancement_agent,
            expected_output="A single JSON object containing 'revised_survey' and 'explanations'.",
            output_format=OutputFormat.JSON
        )

        enhancement_crew = Crew(
            agents=[self.enhancement_agent],
            tasks=[enhancement_task],
            process=Process.sequential,
            verbose=True
        )

        print("\n=== Running AI Enhancement ===")
        enhancement_result = enhancement_crew.kickoff()

        try:
            enhanced_result_raw = enhancement_result.raw
            enhanced_result = _parse_and_clean_json(enhanced_result_raw)
            if 'revised_survey' not in enhanced_result or 'questions' not in enhanced_result['revised_survey']:
                 raise ValueError("The AI's response was missing the required 'revised_survey' structure.")
            self.enhanced_dict = enhanced_result
            return self.enhanced_dict
        except (ValueError, TypeError) as e:
            raise ValueError(f"AI enhancement failed: {e}\\nRaw AI output:\\n{getattr(enhancement_result, 'raw', enhancement_result)}")

# ========== Survey to Qualtrics Conversion ==========
def survey_dict_to_qualtrics_payload(survey_dict: dict) -> dict:
    survey_meta = survey_dict.get("revised_survey", survey_dict.get("survey", {}))
    questions_to_add = {}

    for i, q in enumerate(survey_meta.get("questions", []), 1):
        raw_id = q["question_id"]
        num = re.sub(r'\D+', '', raw_id) or str(i)
        qid = f"QID{num}"

        qobj = {
            "QuestionText": q["question_text"],
            "DataExportTag": qid,
            "QuestionType": "TE",
            "Selector": "SL",
            "Configuration": {"QuestionDescriptionOption": "UseText"},
            "Validation": {"Settings": {"ForceResponse": "OFF", "Type": "None"}}
        }

        it = q["input_type"]
        cfg = q.get("input_config", {})

        if it in ("multiple_choice", "single_choice"):
            choices = {}
            for idx, opt in enumerate(cfg.get("options", []), 1):
                choices[str(idx)] = {"Display": str(opt)}
            qobj.update({
                "QuestionType": "MC",
                "Selector": "SAVR" if it == "multiple_choice" else "SAHR",
                "SubSelector": "TX",
                "Choices": choices
            })
        elif it == "slider":
            qobj.update({
                "QuestionType": "Slider",
                "Selector": "HSLIDER",
                "SubSelector": "HBAR",
                "Configuration": {
                    "QuestionDescriptionOption": "UseText",
                    "CSSliderMin": cfg.get("min", 0),
                    "CSSliderMax": cfg.get("max", 100),
                    "GridLines": cfg.get("step", 1),
                    "NumDecimals": "0",
                    "ShowValue": True
                }
            })
        elif it == "scale":
            scale_min = cfg.get("min", 1)
            scale_max = cfg.get("max", 7)
            scale_labels = cfg.get("labels", {})
            question_text = q["question_text"]
            scale_match = re.search(r'(\d+)\s*=.*?(\d+)\s*=', question_text)
            if scale_match:
                scale_min = int(scale_match.group(1))
                scale_max = int(scale_match.group(2))
            choices = {}
            for i in range(scale_min, scale_max + 1):
                choice_display = scale_labels.get(str(i), str(i))
                choices[str(i)] = {"Display": choice_display}
            qobj.update({
                "QuestionType": "MC",
                "Selector": "SAHR",
                "SubSelector": "TX",
                "Choices": choices
            })
        elif it == "checkbox":
            choices = {}
            for idx, opt in enumerate(cfg.get("options", []), 1):
                choices[str(idx)] = {"Display": str(opt)}
            qobj.update({
                "QuestionType": "MC",
                "Selector": "MAVR",
                "SubSelector": "TX",
                "Choices": choices
            })
        elif it == "text_input":
            qobj.update({
                "QuestionType": "TE",
                "Selector": "SL",
                "Configuration": {"QuestionDescriptionOption": "UseText"}
            })
        else:
            logger.warning(f"Unsupported input_type '{it}' for question {qid}. Using text input.")

        questions_to_add[qid] = qobj

    return {
        "SurveyName": survey_meta.get("theme", "New Survey"),
        "Language": "EN",
        "ProjectCategory": "CORE",
        "Questions": questions_to_add
    }

# ========== Qualtrics API Client ==========
class QualtricsClient:
    def __init__(self):
        load_dotenv()
        self.api_token = os.getenv('QUALTRICS_API_TOKEN')
        self.data_center = os.getenv('QUALTRICS_DATA_CENTER')
        if not self.api_token or not self.data_center:
            raise ValueError("Missing Qualtrics API credentials in environment variables.")
        self.base_url = f"https://{self.data_center}.qualtrics.com/API/v3/"
        self.headers = {"X-API-Token": self.api_token, "Content-Type": "application/json"}
        self.session = requests.Session()
        retries = Retry(total=5, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)
        self.verify = certifi.where()

    def get_survey_questions(self, survey_id: str) -> dict:
        url = f"{self.base_url}survey-definitions/{survey_id}"
        response = self.session.get(url, headers=self.headers, verify=self.verify, timeout=10)
        response.raise_for_status()
        questions = response.json().get("result", {}).get("Questions", {})
        return {q_data.get("DataExportTag", qid): re.sub('<[^<]+?>', '', q_data.get("QuestionText", "")).strip() for qid, q_data in questions.items()}

    def get_survey_responses(self, survey_id: str, file_format="csv") -> pd.DataFrame:
        export_url = f"{self.base_url}surveys/{survey_id}/export-responses"
        resp = self.session.post(export_url, headers=self.headers, json={"format": file_format, "useLabels": True}, verify=self.verify, timeout=10)
        resp.raise_for_status()
        progress_id = resp.json()["result"]["progressId"]

        status = ""
        while status not in ["complete", "failed"]:
            check_url = f"{export_url}/{progress_id}"
            check = self.session.get(check_url, headers=self.headers, verify=self.verify, timeout=10)
            check.raise_for_status()
            result = check.json()["result"]
            status = result["status"]
            print(f"Export status: {status} ({result.get('percentComplete', 0)}%)")
            time.sleep(2)

        if status == "failed":
            raise Exception(f"Export failed: {result.get('errorMessage')}")

        file_id = result["fileId"]
        download_url = f"{export_url}/{file_id}/file"
        dl = self.session.get(download_url, headers=self.headers, verify=self.verify, timeout=60)
        dl.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(dl.content)) as zf:
            fname = next((n for n in zf.namelist() if n.endswith(f".{file_format}")), None)
            if not fname: raise FileNotFoundError(f"No '.{file_format}' file found.")
            with zf.open(fname) as f:
                return pd.read_csv(f, skiprows=[1])

    def create_survey(self, survey_name, survey_template):
        url = f"{self.base_url}survey-definitions"
        simplified_payload = {
            "SurveyName": survey_name,
            "Language": "EN",
            "ProjectCategory": "CORE"
        }
        response = self.session.post(url, headers=self.headers, json=simplified_payload, verify=self.verify, timeout=30)
        if not response.ok:
            logger.error(f"Qualtrics API Error {response.status_code}: {response.text}")
        response.raise_for_status()
        survey_id = response.json()["result"]["SurveyID"]
        if "Questions" in survey_template and survey_template["Questions"]:
            self.add_questions_to_survey(survey_id, survey_template["Questions"])
        return survey_id

    def add_questions_to_survey(self, survey_id: str, questions_dict: dict):
        url = f"{self.base_url}survey-definitions/{survey_id}/questions"
        for question_id, question_data in questions_dict.items():
            try:
                response = self.session.post(url, headers=self.headers, json=question_data, verify=self.verify, timeout=10)
                response.raise_for_status()
            except Exception as e:
                logger.error(f"Error adding question {question_id}: {e}")
                continue

    def activate_survey(self, survey_id):
        url = f"{self.base_url}surveys/{survey_id}"
        response = self.session.put(url, headers=self.headers, json={"isActive": True})
        response.raise_for_status()

    def create_distribution_link(self, survey_id):
        return f"https://{self.data_center}.qualtrics.com/jfe/form/{survey_id}"

# ========== MTurk API Client ==========
class MTurkClient:
    def __init__(self, aws_access_key_id: str = None, aws_secret_access_key: str = None, use_sandbox: bool = True):
        load_dotenv()
        self.aws_access_key_id = aws_access_key_id or os.getenv('AWS_ACCESS_KEY_ID')
        self.aws_secret_access_key = aws_secret_access_key or os.getenv('AWS_SECRET_ACCESS_KEY')
        if not self.aws_access_key_id or not self.aws_secret_access_key:
            raise ValueError("Missing AWS credentials.")
        self.use_sandbox = use_sandbox
        endpoint = 'https://mturk-requester-sandbox.us-east-1.amazonaws.com' if use_sandbox else 'https://mturk-requester.us-east-1.amazonaws.com'
        self.client = boto3.client(
            'mturk',
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            region_name='us-east-1',
            endpoint_url=endpoint
        )

    def create_hit_with_survey_link(self, survey_link, hit_config):
        question_html = f"""<HTMLQuestion xmlns="http://mechanicalturk.amazonaws.com/AWSMechanicalTurkDataSchemas/2011-11-11/HTMLQuestion.xsd">
            <HTMLContent><![CDATA[
                <!DOCTYPE html>
                <html><body>
                <p>Please complete the survey at the following link:</p>
                <p><a href="{survey_link}" target="_blank">{survey_link}</a></p>
                <p>After completing, enter the completion code below:</p>
                <p><input type="text" name="completion_code" size="40"/></p>
                </body></html>
            ]]></HTMLContent><FrameHeight>400</FrameHeight></HTMLQuestion>"""
        response = self.client.create_hit(Question=question_html, **hit_config)
        return response['HIT']['HITId']

    def get_hit_assignments(self, hit_id):
        paginator = self.client.get_paginator('list_assignments_for_hit')
        pages = paginator.paginate(HITId=hit_id)
        return [assignment for page in pages for assignment in page['Assignments']]

# ========== Qualtrics and MTurk Integration ==========
class QualtricsAndMTurkAutomation:
    def __init__(self, mturk_client: Optional[MTurkClient] = None):
        self.qualtrics = QualtricsClient()
        self.mturk = mturk_client or MTurkClient()

    def run(self, survey_payload: dict, hit_config: dict) -> dict:
        survey_id, survey_link = self.deploy_to_qualtrics_only(survey_payload)
        hit_id = self.mturk.create_hit_with_survey_link(survey_link, hit_config)
        return {"survey_id": survey_id, "survey_link": survey_link, "hit_id": hit_id}

    def deploy_to_qualtrics_only(self, survey_payload: dict):
        survey_name = survey_payload.get("SurveyName", "New Survey")
        survey_id = self.qualtrics.create_survey(survey_name, survey_payload)
        self._add_completion_question(survey_id, survey_payload)
        self.qualtrics.activate_survey(survey_id)
        survey_link = self.qualtrics.create_distribution_link(survey_id)
        return survey_id, survey_link

    def _add_completion_question(self, survey_id: str, survey_payload: dict) -> str:
        existing_questions = len(survey_payload.get("Questions", {}))
        comp_qid = f"QID{existing_questions + 1}"
        completion_question = {
            "QuestionText": "Thank you for completing the survey! Your completion code is: ${e://Field/ResponseID}",
            "DataExportTag": f"completion_code_{comp_qid}",
            "QuestionType": "DB",
            "Selector": "TB",
            "Configuration": {"QuestionDescriptionOption": "UseText"}
        }
        url = f"{self.qualtrics.base_url}survey-definitions/{survey_id}/questions"
        response = self.qualtrics.session.post(
            url, headers=self.qualtrics.headers, json=completion_question,
            verify=self.qualtrics.verify, timeout=10
        )
        if not response.ok:
            logger.error(f"Failed to add completion question: {response.status_code} - {response.text}")
        return comp_qid

    def collect_and_process_results(self, survey_id: str, hit_id: Optional[str] = None):
        question_map = self.qualtrics.get_survey_questions(survey_id)
        qualtrics_df = self.qualtrics.get_survey_responses(survey_id)

        if not hit_id:
            return {"responses": self._format_df_with_interleaved_questions(qualtrics_df, question_map)}

        assignments = self.mturk.get_hit_assignments(hit_id)
        if not assignments:
            return {"responses": self._format_df_with_interleaved_questions(qualtrics_df, question_map)}

        mturk_data = []
        for a in assignments:
            try:
                root = ET.fromstring(a['Answer'])
                code_element = root.find(".//{*}Answer[{*}QuestionIdentifier='completion_code']/{*}FreeText")
                mturk_data.append({'WorkerId': a['WorkerId'], 'completion_code': code_element.text if code_element is not None else None})
            except ET.ParseError:
                logger.warning(f"Could not parse XML for assignment {a['AssignmentId']}")

        mturk_df = pd.DataFrame(mturk_data)
        merged_df = pd.merge(qualtrics_df, mturk_df, left_on='ResponseID', right_on='completion_code', how='inner')
        return {"responses": self._format_df_with_interleaved_questions(merged_df, question_map)}

    def _format_df_with_interleaved_questions(self, responses_df: pd.DataFrame, question_map: dict) -> pd.DataFrame:
        if not question_map or responses_df.empty:
            return responses_df
        try:
            question_cols = sorted([col for col in responses_df.columns if col in question_map], key=lambda x: int(re.findall(r'\d+', x)[0]))
        except (IndexError, TypeError):
            question_cols = sorted([col for col in responses_df.columns if col in question_map])
        interleaved_data = {}
        for i, q_col in enumerate(question_cols, 1):
            interleaved_data[f'Question {i}'] = question_map.get(q_col, "Unknown")
            interleaved_data[f'Answer {i}'] = responses_df[q_col]
        return pd.DataFrame(interleaved_data)

# ========== Simulated Data Collection ==========
def collect_simulated_data(template_path: str, survey_context_path: str, participant_csv_path: str) -> pd.DataFrame:
    if not all([run_all_survey_responses_json, openai_llm]):
        raise ImportError("Simulation dependencies (simulate_response module) are not installed in this project.")
    with open(template_path, "r") as f:
        survey_template = f.read()
    with open(survey_context_path, "r") as f:
        survey_context_string = f.read()
    survey_json = json.loads(survey_context_string)
    sim_context = survey_json.get('revised_survey', survey_json)
    responses_df = run_all_survey_responses_json(
        llm=openai_llm,
        participant_csv_path=participant_csv_path,
        survey_prompt_template=survey_template,
        survey_context=json.dumps(sim_context)
    )
    parsed_responses = [json.loads(resp) if isinstance(resp, str) else resp for resp in responses_df['Response']]
    return pd.DataFrame(parsed_responses)

def debias_simulated_data(simulated_data_df: pd.DataFrame, survey_context: dict) -> pd.DataFrame:
    if not run_debias_pipeline:
        raise ImportError("Debias pipeline dependency is not installed.")
    questions = survey_context.get('revised_survey', survey_context).get('questions', [])
    pipeline_input_data = []
    for i, q_data in enumerate(questions):
        answer_col_name = f"Q{i + 1}"
        if answer_col_name in simulated_data_df.columns:
            pipeline_input_data.append({
                "Question": q_data["question_text"],
                "Answers": simulated_data_df[answer_col_name].tolist()
            })
    with tempfile.NamedTemporaryFile(mode='w+', delete=True, suffix='.json', encoding='utf-8') as tmp_input_file, \
         tempfile.NamedTemporaryFile(mode='w+', delete=True, suffix='.json', encoding='utf-8') as tmp_output_file:
        input_filepath = tmp_input_file.name
        output_filepath = tmp_output_file.name
        json.dump(pipeline_input_data, tmp_input_file, indent=4)
        tmp_input_file.flush()
        run_debias_pipeline(input_json=input_filepath, output_json=output_filepath)
        debiased_df = pd.read_json(output_filepath, orient='records')
    return debiased_df

# ========== Research Paper Generation ==========
def generate_research_paper(csv_path: str, hypothesis: Optional[str] = None):
    with open(csv_path, 'r', encoding='utf-8') as f:
        data_summary = f.read(2000)

    analyst_goal = f"Analyze data to find insights related to: '{hypothesis}'" if hypothesis else "Conduct exploratory data analysis."
    data_analyst = Agent(role='Expert Data Analyst', goal=analyst_goal, backstory="You are a meticulous data analyst...", verbose=True)
    academic_writer = Agent(role='Lead Academic Writer', goal="Write a research paper from the analysis.", backstory="You are a professional academic writer...", verbose=True)

    analysis_task = Task(description=f"Analyze the data: {data_summary}", agent=data_analyst, expected_output="A markdown report of the analysis.")
    writing_task = Task(description="Write a full research paper based on the analysis.", agent=academic_writer, context=[analysis_task], expected_output="A complete research paper in markdown.")

    paper_crew = Crew(agents=[data_analyst, academic_writer], tasks=[analysis_task, writing_task], process=Process.sequential, verbose=True)
    result = paper_crew.kickoff()
    return result.raw

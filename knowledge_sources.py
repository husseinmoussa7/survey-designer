import os
import logging
from typing import Optional

try:
    from crewai import Knowledge  # type: ignore
    from crewai.knowledge.source import LocalDirectory  # type: ignore
    _CREWAI_KNOWLEDGE_AVAILABLE = True
except Exception:
    Knowledge = None  # type: ignore
    LocalDirectory = None  # type: ignore
    _CREWAI_KNOWLEDGE_AVAILABLE = False

logger = logging.getLogger(__name__)


def _pdf_source(path: str) -> Optional[object]:
    """Create a LocalDirectory knowledge source for PDFs under a path."""
    if not _CREWAI_KNOWLEDGE_AVAILABLE:
        logger.warning("CrewAI Knowledge APIs not available; skipping knowledge for '%s'", path)
        return None
    if not os.path.isdir(path):
        logger.warning("Knowledge path does not exist or is not a directory: %s", path)
        return None
    try:
        return LocalDirectory(path=path, glob="**/*.pdf")
    except Exception as e:
        logger.warning("Failed to create LocalDirectory knowledge source for %s: %s", path, e)
        return None


def build_unified_pdf_knowledge() -> Optional[object]:
    """Build a single Knowledge object aggregating PDFs from knowledge/ subdirectories.

    Place reference PDFs in knowledge/ subdirectories — they are gitignored.
    """
    if not _CREWAI_KNOWLEDGE_AVAILABLE:
        return None

    knowledge_dir = os.environ.get("KNOWLEDGE_DIR", "knowledge")
    sources = []
    for subdir in ("Sample Papers", "JCR Papers", "New Papers"):
        src = _pdf_source(os.path.join(knowledge_dir, subdir))
        if src is not None:
            sources.append(src)

    # Also accept a flat knowledge/ directory
    if not sources:
        src = _pdf_source(knowledge_dir)
        if src is not None:
            sources.append(src)

    if not sources:
        logger.warning("No knowledge sources discovered; proceeding without knowledge.")
        return None

    try:
        return Knowledge(sources=sources)
    except TypeError:
        try:
            return Knowledge(sources)  # type: ignore
        except Exception as e:
            logger.warning("Failed to construct Knowledge object: %s", e)
            return None
    except Exception as e:
        logger.warning("Failed to construct Knowledge object: %s", e)
        return None


def attach_knowledge_to_crew(crew, knowledge_obj) -> None:
    if knowledge_obj is None:
        return
    try:
        if hasattr(crew, "knowledge"):
            setattr(crew, "knowledge", knowledge_obj)
            return
    except Exception:
        pass
    for method_name in ("add_knowledge", "load_knowledge", "with_knowledge"):
        try:
            if hasattr(crew, method_name):
                getattr(crew, method_name)(knowledge_obj)
                return
        except Exception:
            continue
    logger.warning("Could not attach knowledge to Crew instance using available hooks.")


try:
    _UNIFIED_KNOWLEDGE = build_unified_pdf_knowledge()
except Exception:
    _UNIFIED_KNOWLEDGE = None

initial_crew_knowledge     = _UNIFIED_KNOWLEDGE
enhancement_crew_knowledge = _UNIFIED_KNOWLEDGE
paper_crew_knowledge       = _UNIFIED_KNOWLEDGE

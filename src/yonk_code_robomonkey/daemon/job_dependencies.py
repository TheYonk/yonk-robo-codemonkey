"""
Job Dependency Map - Defines follow-up jobs that should be queued after each job type completes.

This module provides a clear, centralized definition of the job dependency chain:

Indexing Pipeline Flow:
=======================

  FULL_INDEX (reindex all files)
       |
       +---> DOCS_SCAN (scan documentation files)
       |          |
       |          +---> SUMMARIZE_FILES (generate file summaries) [if auto_summaries]
       |          |          |
       |          |          +---> EMBED_SUMMARIES (embed the summaries)
       |          |
       |          +---> SUMMARIZE_SYMBOLS (generate symbol summaries) [if auto_summaries]
       |                     |
       |                     +---> EMBED_SUMMARIES (embed the summaries)
       |
       +---> EMBED_MISSING (embed chunks & documents) [if auto_embed]
       |
       +---> REGENERATE_SUMMARY (regenerate comprehensive repo summary)

  REINDEX_FILE / REINDEX_MANY (incremental reindex)
       |
       +---> EMBED_MISSING (embed new/changed chunks) [if auto_embed]
       |
       +---> REGENERATE_SUMMARY (only for REINDEX_MANY with >5% change)


Priority Levels (lower number = runs first):
=============================================
  10 - FULL_INDEX, REINDEX_FILE, REINDEX_MANY (indexing)
   9 - DOCS_SCAN (doc scanning)
   7 - TAG_RULES_SYNC (tagging)
   5 - EMBED_MISSING (chunk/doc embeddings)
   4 - SUMMARIZE_FILES, SUMMARIZE_SYMBOLS (LLM summaries)
   3 - EMBED_SUMMARIES (summary embeddings)
   2 - REGENERATE_SUMMARY (comprehensive review)


Job Types:
==========
  - FULL_INDEX: Full repository reindex (all files)
  - REINDEX_FILE: Single file reindex
  - REINDEX_MANY: Batch file reindex
  - DOCS_SCAN: Scan and ingest documentation files
  - TAG_RULES_SYNC: Apply tag rules to entities
  - EMBED_MISSING: Generate embeddings for chunks/documents without them
  - EMBED_SUMMARIES: Generate embeddings for file/symbol/module summaries
  - SUMMARIZE_FILES: Generate LLM summaries for files
  - SUMMARIZE_SYMBOLS: Generate LLM summaries for symbols
  - REGENERATE_SUMMARY: Regenerate comprehensive repo summary

"""

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional


class JobType(str, Enum):
    """All supported job types."""
    FULL_INDEX = "FULL_INDEX"
    REINDEX_FILE = "REINDEX_FILE"
    REINDEX_MANY = "REINDEX_MANY"
    DOCS_SCAN = "DOCS_SCAN"
    TAG_RULES_SYNC = "TAG_RULES_SYNC"
    EMBED_MISSING = "EMBED_MISSING"
    EMBED_SUMMARIES = "EMBED_SUMMARIES"
    SUMMARIZE_FILES = "SUMMARIZE_FILES"
    SUMMARIZE_SYMBOLS = "SUMMARIZE_SYMBOLS"
    REGENERATE_SUMMARY = "REGENERATE_SUMMARY"


@dataclass
class FollowUpJob:
    """Definition of a follow-up job to enqueue."""
    job_type: JobType
    priority: int
    dedup_suffix: str  # Appended to repo_name for dedup_key
    condition: Optional[str] = None  # Condition key for checking (e.g., "auto_embed", "auto_summaries")
    condition_job_type: Optional[str] = None  # Only run if parent job type matches


# Job dependency map: parent job type -> list of follow-up jobs
JOB_DEPENDENCIES: dict[JobType, list[FollowUpJob]] = {
    # After FULL_INDEX: scan docs, embed chunks, regenerate summary
    JobType.FULL_INDEX: [
        FollowUpJob(JobType.DOCS_SCAN, priority=9, dedup_suffix="docs_scan"),
        FollowUpJob(JobType.EMBED_MISSING, priority=5, dedup_suffix="embed_missing", condition="auto_embed"),
        FollowUpJob(JobType.REGENERATE_SUMMARY, priority=2, dedup_suffix="regenerate_summary"),
    ],

    # After REINDEX_FILE: just embed (no doc scan or summary regen for single file)
    JobType.REINDEX_FILE: [
        FollowUpJob(JobType.EMBED_MISSING, priority=5, dedup_suffix="embed_missing", condition="auto_embed"),
    ],

    # After REINDEX_MANY: embed, and regen summary if significant changes
    JobType.REINDEX_MANY: [
        FollowUpJob(JobType.EMBED_MISSING, priority=5, dedup_suffix="embed_missing", condition="auto_embed"),
        # Note: REGENERATE_SUMMARY is conditionally enqueued based on change percentage
    ],

    # After DOCS_SCAN: generate file and symbol summaries
    JobType.DOCS_SCAN: [
        FollowUpJob(JobType.SUMMARIZE_FILES, priority=4, dedup_suffix="summarize_files", condition="auto_summaries"),
        FollowUpJob(JobType.SUMMARIZE_SYMBOLS, priority=4, dedup_suffix="summarize_symbols", condition="auto_summaries"),
    ],

    # After SUMMARIZE_FILES: embed the generated summaries
    JobType.SUMMARIZE_FILES: [
        FollowUpJob(JobType.EMBED_SUMMARIES, priority=3, dedup_suffix="embed_summaries", condition="auto_embed"),
    ],

    # After SUMMARIZE_SYMBOLS: embed the generated summaries
    JobType.SUMMARIZE_SYMBOLS: [
        FollowUpJob(JobType.EMBED_SUMMARIES, priority=3, dedup_suffix="embed_summaries", condition="auto_embed"),
    ],

    # After EMBED_MISSING: nothing (end of chain for chunks/docs)
    JobType.EMBED_MISSING: [],

    # After EMBED_SUMMARIES: nothing (end of chain for summaries)
    JobType.EMBED_SUMMARIES: [],

    # After TAG_RULES_SYNC: nothing
    JobType.TAG_RULES_SYNC: [],

    # After REGENERATE_SUMMARY: nothing
    JobType.REGENERATE_SUMMARY: [],
}


def get_follow_up_jobs(job_type: str) -> list[FollowUpJob]:
    """Get the list of follow-up jobs for a given job type.

    Args:
        job_type: The completed job type

    Returns:
        List of FollowUpJob definitions
    """
    try:
        jt = JobType(job_type)
        return JOB_DEPENDENCIES.get(jt, [])
    except ValueError:
        return []


def get_job_priority(job_type: str) -> int:
    """Get the default priority for a job type.

    Lower number = higher priority (runs first).

    Args:
        job_type: The job type

    Returns:
        Priority value (1-10)
    """
    priorities = {
        JobType.FULL_INDEX: 10,
        JobType.REINDEX_FILE: 10,
        JobType.REINDEX_MANY: 10,
        JobType.DOCS_SCAN: 9,
        JobType.TAG_RULES_SYNC: 7,
        JobType.EMBED_MISSING: 5,
        JobType.SUMMARIZE_FILES: 4,
        JobType.SUMMARIZE_SYMBOLS: 4,
        JobType.EMBED_SUMMARIES: 3,
        JobType.REGENERATE_SUMMARY: 2,
    }
    try:
        return priorities.get(JobType(job_type), 5)
    except ValueError:
        return 5


def get_all_job_types() -> list[str]:
    """Get all supported job type names."""
    return [jt.value for jt in JobType]


def print_dependency_tree():
    """Print the job dependency tree for documentation/debugging."""
    print("\nJob Dependency Tree:")
    print("=" * 50)

    def print_deps(job_type: JobType, indent: int = 0):
        prefix = "  " * indent
        deps = JOB_DEPENDENCIES.get(job_type, [])
        for dep in deps:
            cond = f" [if {dep.condition}]" if dep.condition else ""
            print(f"{prefix}└── {dep.job_type.value} (priority={dep.priority}){cond}")
            print_deps(dep.job_type, indent + 1)

    # Start from root job types (indexing jobs)
    for root in [JobType.FULL_INDEX, JobType.REINDEX_FILE, JobType.REINDEX_MANY]:
        print(f"\n{root.value}:")
        print_deps(root)


if __name__ == "__main__":
    # Print dependency tree when run directly
    print_dependency_tree()

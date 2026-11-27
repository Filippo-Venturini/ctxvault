"""LongMemEval harness: replay sessions into a vault, answer, grade, report.

Design agreed in Filippo-Venturini/ctxvault#41 and scoped in #47.
The official dataset is not stored in the repository; it is downloaded into
a cache and checked against a pinned SHA-256.
"""

__all__ = [
    "SPLITS",
    "load_questions",
    "download_split",
    "parse_lme_datetime",
    "question_instant",
    "run",
    "write_report",
]

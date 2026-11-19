"""Two independent grades for one hypothesis: a word-overlap grader, and a judge."""

from __future__ import annotations

import re

from benchmarks.longmemeval.chat import ChatClient
from benchmarks.longmemeval.data import Question
from benchmarks.longmemeval.prompts import JUDGE_PROMPT_VERSION, judge_prompt

# Function words dropped before the overlap check. The gold answer's remaining
# tokens are the "content words" #47 asks the deterministic grader to test.
_STOP = frozenset(
    """
    a an the and or but if then so than as of to in on at by for from with
    about into over after before between through during without within until
    is are was were be been being am do does did doing have has had having
    will would can could should may might must
    i me my mine we us our you your yours he him his she her hers it its
    they them their this that these those there here what which who whom
    when where why how not no nor
    """.split()
)
_TOKEN = re.compile(r"[a-z0-9]+")


def content_words(text: str) -> list[str]:
    return [token for token in _TOKEN.findall(text.lower()) if token not in _STOP]


def grader_correct(hypothesis: str, gold: str) -> bool:
    """True when every content word of the gold answer appears in the hypothesis.

    If the gold answer has no content words (a bare number, a single stop
    word), the check falls back to the gold string appearing in the hypothesis,
    case-insensitive.
    """
    gold_words = content_words(gold)
    if not gold_words:
        needle = gold.strip().lower()
        return bool(needle) and needle in hypothesis.lower()
    have = set(content_words(hypothesis))
    return all(word in have for word in gold_words)


def parse_yes_no(text: str) -> bool:
    """The official script treats a reply as correct when it contains 'yes'."""
    return "yes" in text.lower()


def judge_correct(
    question: Question,
    hypothesis: str,
    client: ChatClient,
    model: str,
) -> bool:
    reply = client.complete(
        model,
        stage="judge",
        user=judge_prompt(question, hypothesis),
        max_tokens=10,
    )
    return parse_yes_no(reply.text)


__all__ = [
    "JUDGE_PROMPT_VERSION",
    "content_words",
    "grader_correct",
    "parse_yes_no",
    "judge_correct",
]

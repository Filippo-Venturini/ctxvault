"""Prompts used to answer a question and to judge the answer.

The judge templates are the official LongMemEval `evaluate_qa.py` prompts,
kept verbatim so a hypotheses.jsonl from this harness can be compared with
a run of that script. The answer prompt is ours; its version is recorded in
the manifest.
"""

from __future__ import annotations

from benchmarks.longmemeval.data import Question, Session, to_iso

ANSWER_PROMPT_VERSION = "lme-answer-1"
JUDGE_PROMPT_VERSION = "longmemeval-evaluate_qa"

ANSWER_SYSTEM = """You answer a question from the memory provided below, and from nothing else.
The date of the question is given; treat it as "now".
If the memory is not enough to answer, say that you do not have that information.
Reply with the answer only."""


def format_session(session: Session) -> str:
    lines = [f"Session {session.id} ({session.date})"]
    for turn in session.turns:
        lines.append(f"{turn.role}: {turn.content}")
    return "\n".join(lines)


def format_history(sessions: tuple[Session, ...] | list[Session]) -> str:
    return "\n\n".join(format_session(session) for session in sessions)


def answer_prompt(question: Question, memory: str) -> tuple[str, str]:
    asked = to_iso(question.question_date)
    user = (
        f"Today is {asked}.\n\n"
        f"Memory:\n{memory}\n\n"
        f"Question: {question.question}"
    )
    return ANSWER_SYSTEM, user


def judge_prompt(question: Question, hypothesis: str) -> str:
    """The official LongMemEval yes/no judge prompt for this question type."""
    task = question.question_type
    q, answer, response = question.question, question.answer, hypothesis
    if question.abstention:
        return (
            "I will give you an unanswerable question, an explanation, and a response from a model. "
            "Please answer yes if the model correctly identifies the question as unanswerable. "
            "The model could say that the information is incomplete, or some other information is given "
            "but the asked information is not.\n\n"
            f"Question: {q}\n\nExplanation: {answer}\n\nModel Response: {response}\n\n"
            "Does the model correctly identify the question as unanswerable? Answer yes or no only."
        )
    if task in ("single-session-user", "single-session-assistant", "multi-session"):
        return (
            "I will give you a question, a correct answer, and a response from a model. "
            "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
            "If the response is equivalent to the correct answer or contains all the intermediate "
            "steps to get the correct answer, you should also answer yes. If the response only "
            "contains a subset of the information required by the answer, answer no. \n\n"
            f"Question: {q}\n\nCorrect Answer: {answer}\n\nModel Response: {response}\n\n"
            "Is the model response correct? Answer yes or no only."
        )
    if task == "temporal-reasoning":
        return (
            "I will give you a question, a correct answer, and a response from a model. "
            "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
            "If the response is equivalent to the correct answer or contains all the intermediate "
            "steps to get the correct answer, you should also answer yes. If the response only "
            "contains a subset of the information required by the answer, answer no. In addition, "
            "do not penalize off-by-one errors for the number of days. If the question asks for the "
            "number of days/weeks/months, etc., and the model makes off-by-one errors (e.g., "
            "predicting 19 days when the answer is 18), the model's response is still correct. \n\n"
            f"Question: {q}\n\nCorrect Answer: {answer}\n\nModel Response: {response}\n\n"
            "Is the model response correct? Answer yes or no only."
        )
    if task == "knowledge-update":
        return (
            "I will give you a question, a correct answer, and a response from a model. "
            "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
            "If the response contains some previous information along with an updated answer, the "
            "response should be considered as correct as long as the updated answer is the required "
            "answer.\n\n"
            f"Question: {q}\n\nCorrect Answer: {answer}\n\nModel Response: {response}\n\n"
            "Is the model response correct? Answer yes or no only."
        )
    if task == "single-session-preference":
        return (
            "I will give you a question, a rubric for desired personalized response, and a response "
            "from a model. Please answer yes if the response satisfies the desired response. "
            "Otherwise, answer no. The model does not need to reflect all the points in the rubric. "
            "The response is correct as long as it recalls and utilizes the user's personal "
            "information correctly.\n\n"
            f"Question: {q}\n\nRubric: {answer}\n\nModel Response: {response}\n\n"
            "Is the model response correct? Answer yes or no only."
        )
    raise ValueError(f"No LongMemEval judge prompt for question type {task!r}.")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Nov  9 13:30:50 2026

@author: louis
"""

import random

from notes_maker import client, MODEL_CHEAP, MAX_CHARS
from pdf_reader import extract_pdf_text

# The stronger (and pricier) model, for hard material
MODEL_STRONG = "claude-sonnet-5-5"

QUIZ_INSTRUCTIONS = """You are a university quiz writer.
Write multiple-choice questions from the lecture text you are given,
by calling the save_quiz tool exactly once.

Rules:
- Use ONLY information found in the lecture text. Do not invent facts or numbers.
- Test understanding, not trivia. Do not ask about slide numbers, the lecturer or admin details.
- Write each question so it stands alone, like a real exam question. Do not begin
  with "According to the lecture" or anything similar.
- Every question has exactly 4 options and exactly one clearly correct answer.
- Wrong options must be real concepts, terms or values that a student could plausibly
  confuse with the right answer, such as common misconceptions or near-miss values.
  No nonsense options.
- Make all four options similar in length, detail and wording style. The correct
  answer must NOT tend to be the longest option, so give the wrong options the same
  level of detail as the right one.
- Keep every option at most 20 words. Vary which option is longest: the correct
  answer must be the longest option in no more than about a quarter of the questions.
- Never use "all of the above" or "none of the above".
- Mix easier and harder questions. Each question should cover a different part of the lecture.
- topic: a short label of 2-4 words for the concept being tested.
- explanation: 1-3 sentences saying why the correct answer is right and why the most
  tempting wrong answer is wrong. NEVER refer to options by letter or position
  (no "option B", no "the first answer"). Refer to answers by what they say.
- Do not write questions about content that seems missing from the text."""

# The "form" Claude fills in for the quiz
QUIZ_TOOL = {
    "name": "save_quiz",
    "description": "Save the finished quiz questions.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "question": {"type": "string"},
                        "options": {"type": "array", "items": {"type": "string"}},
                        "correct_index": {"type": "integer", "description": "0 to 3: position of the correct option"},
                        "explanation": {"type": "string"},
                    },
                    "required": ["topic", "question", "options", "correct_index", "explanation"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["questions"],
        "additionalProperties": False,
    },
}


def clean_question(q):
    """Check one question is well-formed, then shuffle its options. Returns None if it is bad."""
    options = q.get("options")
    if not isinstance(options, list) or len(options) != 4:
        return None
    if not all(isinstance(o, str) and o.strip() for o in options):
        return None
    if len(set(options)) != 4:
        return None
    if q.get("correct_index") not in (0, 1, 2, 3):
        return None
    if not q.get("question") or not q.get("explanation"):
        return None

    correct_text = options[q["correct_index"]]
    shuffled = options[:]          # make a copy so we do not change the original
    random.shuffle(shuffled)

    return {
        "topic": q.get("topic", ""),
        "question": q["question"],
        "options": shuffled,
        "correct_index": shuffled.index(correct_text),
        "explanation": q["explanation"],
    }


def generate_quiz(lecture_text, n_questions=8, style_hint="", model=MODEL_CHEAP):
    """Returns (list of questions, tokens_in, tokens_out)."""
    if len(lecture_text) > MAX_CHARS:
        raise ValueError("This file has too much text. Please upload a shorter one.")

    instructions = QUIZ_INSTRUCTIONS + f"\n- Write exactly {n_questions} questions."
    if style_hint:
        instructions += "\n- Question style for this course: " + style_hint

    total_in = 0
    total_out = 0

    # Try up to 2 times, in case the form comes back faulty
    for attempt in range(2):
        response = client.messages.create(
            model=model,
            max_tokens=8000,
            system=instructions,
            tools=[QUIZ_TOOL],
            messages=[
                {"role": "user", "content": "Here is the lecture text:\n\n" + lecture_text}
            ],
        )
        total_in += response.usage.input_tokens
        total_out += response.usage.output_tokens

        if response.stop_reason == "max_tokens":
            raise ValueError("The quiz was cut off because it hit the length limit. Try a shorter file.")

        for block in response.content:
            if block.type == "tool_use" and block.name == "save_quiz":
                raw = block.input.get("questions", [])
                good = [clean_question(q) for q in raw]
                good = [q for q in good if q is not None]
                # Accept the quiz if at least half the questions passed the checks
                if len(good) >= (n_questions + 1) // 2:
                    return good, total_in, total_out

        print(f"Attempt {attempt + 1}: the quiz came back faulty, trying again...")

    raise ValueError("Claude did not return a usable quiz. Please try again.")


# Quick self-test. Run:  python quiz_maker.py          (cheap model)
#                  or:   python quiz_maker.py strong   (stronger model)
if __name__ == "__main__":
    import sys

    use_strong = len(sys.argv) > 1 and sys.argv[1] == "strong"
    model = MODEL_STRONG if use_strong else MODEL_CHEAP
    price_in, price_out = (2.00, 10.00) if use_strong else (0.10, 0.50)

    text, pages = extract_pdf_text("sample.pdf")
    questions, tokens_in, tokens_out = generate_quiz(text, model=model)

    print("MODEL:", model)
    print()
    for number, q in enumerate(questions, start=1):
        print(f"Q{number} [{q['topic']}] {q['question']}")
        for i, option in enumerate(q["options"]):
            marker = "  <-- correct" if i == q["correct_index"] else ""
            print(f"   {'ABCD'[i]}. {option}{marker}")
        print("   Why:", q["explanation"])
        print()

    print("Questions:", len(questions))
    print("Tokens in:", tokens_in)
    print("Tokens out:", tokens_out)
    cost = tokens_in * price_in / 1_000_000 + tokens_out * price_out / 1_000_000
    print(f"Estimated cost: ${cost:.5f}")
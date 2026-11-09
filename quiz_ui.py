from collections import Counter

import streamlit as st

from display import safe


def start_quiz():
    """Reset the quiz: go back to question 1 and forget all answers."""
    st.session_state["quiz_index"] = 0      # which question we are on (0 = the first)
    st.session_state["quiz_answers"] = {}   # {question number: option the person clicked}
    st.session_state.pop("attempt_saved", None)   # so a retake saves a fresh score
    st.session_state["flagged_qs"] = set()  # questions reported during this run


def clear_quiz():
    """Throw away the current quiz and all its progress."""
    for key in ["quiz", "quiz_id", "quiz_title", "quiz_info", "quiz_index",
                "quiz_answers", "wrong_answers", "attempt_saved", "flagged_qs"]:
        st.session_state.pop(key, None)


def _choose(question_number, option_number):
    """Runs the moment an option is clicked: remember which option was picked."""
    st.session_state["quiz_answers"][question_number] = option_number


def _next():
    """Runs when 'Next question' is clicked: move on one question."""
    st.session_state["quiz_index"] += 1


def _flag(question_number, q, on_flag):
    """Runs when the report button is clicked. on_flag saves it and returns True if it worked."""
    if on_flag(q):
        st.session_state["flagged_qs"].add(question_number)


def render_quiz(questions, on_flag=None):
    """Draw the current question. Shows feedback once an option is clicked."""
    if "quiz_index" not in st.session_state:
        start_quiz()

    index = st.session_state["quiz_index"]
    answers = st.session_state["quiz_answers"]
    total = len(questions)

    # Past the last question: show the results screen
    if index >= total:
        render_results(questions)
        return

    q = questions[index]
    answered = index in answers

    st.progress(index / total, text=f"Question {index + 1} of {total}")
    st.caption("Topic: " + safe(q["topic"]))
    st.markdown("**" + safe(q["question"]) + "**")

    # One button per option
    for j, option in enumerate(q["options"]):
        label = f"{'ABCD'[j]}. {safe(option)}"
        if answered:
            if j == q["correct_index"]:
                label = "✅ " + label
            elif j == answers[index]:
                label = "❌ " + label
        st.button(
            label,
            key=f"q{index}_option{j}",
            disabled=answered,
            on_click=_choose,
            args=(index, j),
            use_container_width=True,
        )

    # After answering: feedback, explanation, report button, and a button to move on
    if answered:
        if answers[index] == q["correct_index"]:
            st.success("Correct!")
        else:
            st.error("Not quite.")
        st.info(safe(q["explanation"]))

        if on_flag is not None:
            flagged = st.session_state.setdefault("flagged_qs", set())
            if index in flagged:
                st.caption("🚩 Reported. It won't come back in revision or mixed practice.")
            else:
                st.button("🚩 This question looks wrong", key=f"flag{index}",
                          on_click=_flag, args=(index, q, on_flag))

        next_label = "Next question" if index + 1 < total else "Finish quiz"
        st.button(next_label, on_click=_next, type="primary")


def render_results(questions):
    """Final score, a review of every mistake, and a list of weak topics."""
    answers = st.session_state["quiz_answers"]
    total = len(questions)

    # Build a list of everything the person got wrong
    wrong = []
    for i, q in enumerate(questions):
        picked = answers.get(i)
        if picked != q["correct_index"]:
            wrong.append({
                "topic": q["topic"],
                "question": q["question"],
                "options": q["options"],
                "correct_index": q["correct_index"],
                "picked_index": picked,
                "explanation": q["explanation"],
            })
    st.session_state["wrong_answers"] = wrong

    score = total - len(wrong)
    percent = round(100 * score / total)

    st.header(f"Your score: {score} / {total}  ({percent}%)")
    st.progress(score / total)

    if percent == 100:
        st.balloons()
        st.success("Perfect score!")
    elif percent >= 70:
        st.success("Nice work. Have a look at the ones you missed.")
    else:
        st.warning("Worth another pass. Review the mistakes below, then retake.")

    if wrong:
        st.subheader("Topics to revise")
        counts = Counter(w["topic"] for w in wrong)
        for topic, number in counts.most_common():
            st.write(f"- {safe(topic)} ({number} wrong)")

        st.subheader("Your mistakes")
        for w in wrong:
            with st.expander(safe(w["question"])):
                if w["picked_index"] is not None:
                    st.error("You chose: " + safe(w["options"][w["picked_index"]]))
                st.success("Correct answer: " + safe(w["options"][w["correct_index"]]))
                st.info(safe(w["explanation"]))

    col1, col2 = st.columns(2)
    with col1:
        st.button("Retake this quiz", on_click=start_quiz, use_container_width=True)
    with col2:
        st.button("Make a new quiz", on_click=clear_quiz, use_container_width=True)
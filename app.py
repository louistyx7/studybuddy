import config  # noqa: F401  (loads the keys before anything else needs them)
import random
from collections import Counter

import anthropic
import streamlit as st

import db
from auth import require_login
from course_styles import STYLE_HINTS
from display import render_notes, safe
from file_reader import extract_text
from notes_maker import generate_notes
from quiz_maker import generate_quiz, MODEL_CHEAP, MODEL_STRONG
from quiz_ui import render_quiz, start_quiz, clear_quiz

MAX_MB = 10  # biggest file we accept
PRICES = {MODEL_CHEAP: (0.10, 0.50), MODEL_STRONG: (2.00, 10.00)}  # per million tokens
STYLE_LABELS = {"general": "General", "finance": "Finance", "physio": "Physiotherapy"}
REVISION_SIZE = 10  # questions per revision round

st.set_page_config(page_title="StudyBuddy", page_icon="📚")
sb = require_login()  # the page stops here until someone is signed in


def cost_of(model, tokens_in, tokens_out):
    price_in, price_out = PRICES[model]
    return tokens_in * price_in / 1_000_000 + tokens_out * price_out / 1_000_000


def run_safely(action, *args):
    """Run action(*args). Returns True if it worked, False if it failed (after showing a message)."""
    try:
        action(*args)
        return True
    except ValueError as error:
        st.error(str(error))  # our own friendly messages
    except anthropic.APIError as error:
        print("Claude API error:", error)
        st.error("Claude could not be reached right now. Please try again in a minute.")
    except Exception as error:
        print("Unexpected error:", error)
        if "JWT" in str(error):
            st.error("Your login has expired. Please log out and log in again.")
        else:
            st.error("Something went wrong. Please try again, or try another file.")
    return False


def create_course(name, style):
    row = db.add_course(sb, name.strip(), style)
    st.session_state["course_id"] = row["id"]  # select the new course


def add_lecture(course, uploaded):
    with st.spinner("Reading the file..."):
        text, pages = extract_text(uploaded, uploaded.name)
    if len(text.strip()) < 200:
        raise ValueError("I could not find much text. This file may be mostly images or a scan.")
    row = db.save_document(sb, course["id"], uploaded.name, pages, text)
    st.session_state[f"doc_{course['id']}"] = row["id"]  # select the new lecture
    st.session_state["uploader_n"] = st.session_state.get("uploader_n", 0) + 1  # empty the uploader


def load_doc(doc_id):
    """Fetch the full lecture row once, then remember it (the text can be large)."""
    cached = st.session_state.get("loaded_doc")
    if cached and cached["id"] == doc_id:
        return cached
    row = db.get_document(sb, doc_id)
    st.session_state["loaded_doc"] = row
    return row


def make_notes(doc, model):
    with st.spinner("Asking Claude for notes..."):
        notes, tokens_in, tokens_out = generate_notes(doc["lecture_text"], model=model)
    db.save_notes(sb, doc["id"], notes)
    doc["notes"] = notes
    st.session_state["notes_info"] = (
        f"{tokens_in} in | {tokens_out} out | about ${cost_of(model, tokens_in, tokens_out):.4f}"
    )


def make_quiz(course, doc, model, n_questions):
    with st.spinner("Asking Claude for a quiz..."):
        questions, tokens_in, tokens_out = generate_quiz(
            doc["lecture_text"],
            n_questions=n_questions,
            style_hint=STYLE_HINTS[course["style"]],
            model=model,
        )
    row = db.save_quiz(sb, doc["id"], model, questions)
    clear_quiz()
    st.session_state["quiz"] = questions
    st.session_state["quiz_id"] = row["id"]
    st.session_state["quiz_info"] = (
        f"{len(questions)} questions | {tokens_in} in | {tokens_out} out | "
        f"about ${cost_of(model, tokens_in, tokens_out):.4f}"
    )
    start_quiz()


def open_quiz(row):
    """Runs when 'Open quiz' is clicked: load a saved quiz (free, no Claude)."""
    clear_quiz()
    st.session_state["quiz"] = row["questions"]
    st.session_state["quiz_id"] = row["id"]
    start_quiz()


def start_revision(missed):
    """Runs when 'Start revision' is clicked: replay the most-missed questions (free)."""
    chosen = sorted(missed, key=lambda m: -m["times_wrong"])[:REVISION_SIZE]
    questions = [m["question"] for m in chosen]
    random.shuffle(questions)
    clear_quiz()
    st.session_state["quiz"] = questions
    st.session_state["quiz_id"] = None  # a revision round is not a saved quiz
    st.session_state["quiz_title"] = "🔁 Revision round"
    start_quiz()


def save_result(course_id, quiz):
    """Save the score (normal quizzes) and update the missed-questions list (all quizzes)."""
    answers = st.session_state["quiz_answers"]
    wrong = st.session_state.get("wrong_answers", [])
    quiz_id = st.session_state.get("quiz_id")
    if quiz_id:
        db.save_attempt(sb, quiz_id, len(quiz) - len(wrong), len(quiz), wrong)
    db.record_results(sb, course_id, quiz, answers)


# ---------- Sidebar: courses ----------
courses = db.list_courses(sb)

with st.sidebar:
    st.divider()
    with st.expander("➕ New course", expanded=not courses):
        new_name = st.text_input("Course name", key="new_course_name")
        new_style = st.selectbox("Type", list(STYLE_LABELS), format_func=STYLE_LABELS.get, key="new_course_style")
        if st.button("Create course"):
            if not new_name.strip():
                st.error("Please type a course name.")
            elif run_safely(create_course, new_name, new_style):
                st.rerun()

    if courses:
        names = {c["id"]: c["name"] for c in courses}
        st.selectbox("Course", list(names), format_func=names.get, key="course_id")

if not courses:
    st.title("📚 StudyBuddy")
    st.info("Create your first course in the sidebar to get started.")
    st.stop()

course = next(c for c in courses if c["id"] == st.session_state["course_id"])
st.title(f"📚 {course['name']}")
st.caption("Course type: " + STYLE_LABELS[course["style"]])

# A different course than last time? Close any open quiz.
if st.session_state.get("active_course") != course["id"]:
    clear_quiz()
    st.session_state["active_course"] = course["id"]

# ---------- An open quiz takes over the whole page ----------
if "quiz" in st.session_state:
    quiz = st.session_state["quiz"]
    if st.session_state.get("quiz_title"):
        st.subheader(st.session_state["quiz_title"])
    render_quiz(quiz)

    # Save the result once, the first time the results screen appears
    if st.session_state["quiz_index"] >= len(quiz) and not st.session_state.get("attempt_saved"):
        if run_safely(save_result, course["id"], quiz):
            st.session_state["attempt_saved"] = True

    if st.session_state.get("quiz_info"):
        st.caption(st.session_state["quiz_info"])
    st.button("Close this quiz", on_click=clear_quiz)
    st.stop()

# ---------- Add a lecture ----------
docs = db.list_documents(sb, course["id"])

with st.expander("⬆️ Add a lecture", expanded=not docs):
    uploaded = st.file_uploader(
        "PDF or PowerPoint", type=["pdf", "pptx"],
        key=f"uploader_{st.session_state.get('uploader_n', 0)}",
    )
    if uploaded is not None:
        if uploaded.size > MAX_MB * 1024 * 1024:
            st.error(f"That file is over {MAX_MB} MB. Please choose a smaller one.")
        elif any(d["filename"] == uploaded.name for d in docs):
            st.warning("A lecture with this file name is already in this course.")
        elif st.button("Save lecture to this course"):
            if run_safely(add_lecture, course, uploaded):
                st.rerun()

if not docs:
    st.info("No lectures in this course yet. Add one above.")
    st.stop()

# ---------- Pick a lecture ----------
labels = {d["id"]: f"{d['filename']}  ({d['created_at'][:10]})" for d in docs}
doc_id = st.selectbox("Lecture", list(labels), format_func=labels.get, key=f"doc_{course['id']}")
doc = load_doc(doc_id)

if st.session_state.get("active_doc") != doc_id:
    st.session_state.pop("notes_info", None)
    st.session_state["active_doc"] = doc_id

use_strong = st.checkbox("Use the stronger model (about 20x the price)")
model = MODEL_STRONG if use_strong else MODEL_CHEAP

tab_notes, tab_quiz, tab_revise = st.tabs(["📝 Notes", "❓ Quiz", "🔁 Revise mistakes"])

# ---------- Notes ----------
with tab_notes:
    if doc["notes"]:
        render_notes(doc["notes"])
        if st.session_state.get("notes_info"):
            st.caption(st.session_state["notes_info"])
        st.caption("These notes are a first draft. Check numbers against your original slides.")
    elif st.button("📝 Make study notes"):
        if run_safely(make_notes, doc, model):
            st.rerun()

# ---------- Quiz ----------
with tab_quiz:
    n_questions = st.slider("Number of quiz questions", 4, 12, 8)
    if st.button("❓ Make a new quiz"):
        if run_safely(make_quiz, course, doc, model, n_questions):
            st.rerun()

    saved = db.list_quizzes(sb, doc_id)
    if saved:
        st.divider()
        by_id = {q["id"]: q for q in saved}
        quiz_labels = {
            q["id"]: f"{q['created_at'][:10]}: {len(q['questions'])} questions" for q in saved
        }
        chosen = st.selectbox("Saved quizzes", list(quiz_labels), format_func=quiz_labels.get,
                              key=f"saved_quiz_{doc_id}")
        st.button("Open quiz", on_click=open_quiz, args=(by_id[chosen],))

        history = [a for a in db.recent_attempts(sb) if a["quiz_id"] in by_id][:5]
        if history:
            st.write("**Your recent scores**")
            for a in history:
                st.write(f"- {a['created_at'][:10]}: {a['score']} / {a['total']}")

# ---------- Revise mistakes (whole course) ----------
with tab_revise:
    missed = db.list_missed(sb, course["id"])
    if not missed:
        st.success("Nothing to revise yet. Questions you get wrong in quizzes collect here.")
    else:
        st.write(f"**{len(missed)} question(s)** from this course still to master.")
        for topic, number in Counter(m["topic"] for m in missed).most_common():
            st.write(f"- {safe(topic)} ({number})")
        st.caption(
            f"A revision round replays up to {REVISION_SIZE} of your most-missed questions. "
            "It is free (no Claude call). Answer one correctly and it leaves this list."
        )
        st.button("🔁 Start revision round", on_click=start_revision, args=(missed,))
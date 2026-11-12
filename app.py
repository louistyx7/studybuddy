import config  # noqa: F401  (loads the keys before anything else needs them)
import html
import random
from collections import Counter
from pathlib import Path

import anthropic
import streamlit as st
import streamlit.components.v1 as components

import db
from auth import require_login
from course_styles import STYLE_HINTS
from display import render_notes, safe
from file_reader import extract_text
from notes_maker import generate_notes
from quiz_maker import generate_quiz, MODEL_CHEAP, MODEL_STRONG
from quiz_ui import render_quiz, start_quiz, clear_quiz
from study_guide import generate_guide, render_html, DETAIL_LEVELS
from ui import inject_css, hero

MAX_MB = 10  # biggest file we accept
PRICES = {MODEL_CHEAP: (0.10, 0.50), MODEL_STRONG: (2.00, 10.00)}  # per million tokens
STYLE_LABELS = {"general": "General", "finance": "Finance", "physio": "Physiotherapy"}
STYLE_ACCENTS = {"general": "#475569", "finance": "#2563EB", "physio": "#0F766E"}
MODEL_CHOICES = {
    "Standard (Cheapest)": MODEL_CHEAP,
    "Stronger (About 20x the Price)": MODEL_STRONG,
}
# Module colours: (circle shown in menus, colour used on the page and in guides)
MODULE_COLOURS = {
    "blue": ("🔵", "#2563EB"),
    "green": ("🟢", "#16A34A"),
    "purple": ("🟣", "#7C3AED"),
    "orange": ("🟠", "#EA580C"),
    "red": ("🔴", "#DC2626"),
    "yellow": ("🟡", "#CA8A04"),
    "brown": ("🟤", "#92400E"),
}
GUIDE_DEFAULTS = {  # which extras are on by default for each course type
    "general": dict(tables=True, charts=False, diagrams=True, examples=False, pearls=True, extras=False),
    "finance": dict(tables=True, charts=True, diagrams=True, examples=True, pearls=True, extras=False),
    "physio": dict(tables=True, charts=False, diagrams=False, examples=False, pearls=True, extras=False),
}
GUIDE_LABELS = {
    "tables": "Tables", "charts": "Charts and Graphs", "diagrams": "Flow Diagrams",
    "examples": "Formulas and Worked Examples", "pearls": "Exam Pearls",
    "extras": "Extra Topics Beyond the Slides",
}
SORTS = ["Newest First", "Oldest First", "Name (A to Z)"]
REVISION_SIZE = 10  # questions per revision round
MAX_NAME_LENGTH = 60  # longest quiz name we accept

st.set_page_config(page_title="StudyBuddy", page_icon="📚")
inject_css()
sb = require_login()  # the page stops here until someone is signed in


# ---------- Small helpers ----------
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
    except anthropic.BadRequestError as error:
        print("Claude rejected the request:", error)
        st.error(f"Claude rejected the request: {error}")
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


def act(action, *args, done=None):
    """For button callbacks: run action(*args), then show a small pop-up message."""
    try:
        action(*args)
        if done:
            st.toast(done)
    except ValueError as error:
        st.toast(f"⚠️ {error}")
    except Exception as error:
        print("Action failed:", error)
        if "JWT" in str(error):
            st.toast("⚠️ Your login has expired. Please log out and log in again.")
        else:
            st.toast("⚠️ Something went wrong. Please try again.")


def colour_info(name):
    return MODULE_COLOURS.get(name, MODULE_COLOURS["blue"])


def colour_label(name):
    return f"{colour_info(name)[0]} {name.title()}"


def next_free_colour(modules):
    used = {m["colour"] for m in modules}
    free = [c for c in MODULE_COLOURS if c not in used]
    return free[0] if free else list(MODULE_COLOURS)[len(modules) % len(MODULE_COLOURS)]


def sort_docs(items, how):
    if how == "Oldest First":
        return sorted(items, key=lambda d: d["created_at"])
    if how == "Name (A to Z)":
        return sorted(items, key=lambda d: d["filename"].lower())
    return sorted(items, key=lambda d: d["created_at"], reverse=True)


def module_label(value, docs, module_by_id, unsorted_count):
    if value == "all":
        return f"📚 All Lectures ({len(docs)})"
    if value == "none":
        return f"📂 Unsorted ({unsorted_count})"
    m = module_by_id[value]
    count = sum(1 for d in docs if d["module_id"] == value)
    return f"{colour_info(m['colour'])[0]} {m['name']} ({count})"


def doc_label(d, module_by_id, selected):
    m = module_by_id.get(d["module_id"])
    tag = f"{colour_info(m['colour'])[0]} " if (m and selected == "all") else ""
    return f"{tag}{d['filename']}"


def remember_sort():
    st.session_state["sort_pref"] = st.session_state.get("sort_widget", SORTS[0])


# ---------- Actions (all run from buttons) ----------
def do_create_course():
    name = st.session_state.get("new_course_name", "").strip()
    if not name:
        raise ValueError("Please type a course name.")
    row = db.add_course(sb, name, st.session_state.get("new_course_style", "general"))
    st.session_state["course_id"] = row["id"]  # select the new course
    st.session_state["new_course_name"] = ""


def do_rename_course(course_id):
    db.rename_course(sb, course_id, st.session_state.get(f"rn_course_{course_id}", ""))


def do_delete_course(course_id):
    db.delete_course(sb, course_id)
    for key in ("course_id", "loaded_doc", "active_doc", "nav_sig"):
        st.session_state.pop(key, None)
    clear_quiz()


def do_add_module(course):
    cid = course["id"]
    name = st.session_state.get(f"new_mod_name_{cid}", "").strip()
    if not name:
        raise ValueError("Please type a module name.")
    colour = st.session_state.get(f"new_mod_colour_{cid}", "blue")
    modules = db.list_modules(sb, cid)
    position = max([m["position"] for m in modules], default=-1) + 1
    row = db.add_module(sb, cid, name, colour, position)
    st.session_state[f"mod_{cid}"] = row["id"]  # jump to the new module
    st.session_state[f"new_mod_name_{cid}"] = ""
    st.session_state[f"new_mod_colour_{cid}"] = next_free_colour(modules + [row])


def do_update_module(module_id):
    name = st.session_state.get(f"rn_mod_{module_id}", "").strip()
    if not name:
        raise ValueError("Please type a module name.")
    db.update_module(sb, module_id, {"name": name, "colour": st.session_state.get(f"col_mod_{module_id}", "blue")})


def do_move_module(course_id, module_id, step):
    modules = db.list_modules(sb, course_id)
    ids = [m["id"] for m in modules]
    i = ids.index(module_id)
    j = i + step
    if 0 <= j < len(modules):
        db.swap_modules(sb, modules[i], modules[j])


def do_delete_module(course_id, module_id):
    db.delete_module(sb, module_id)
    st.session_state[f"mod_{course_id}"] = "all"
    st.session_state.pop(f"doc_{course_id}", None)
    st.session_state.pop("loaded_doc", None)


def do_rename_doc(doc_id):
    name = st.session_state.get(f"rn_doc_{doc_id}", "").strip()
    if not name:
        raise ValueError("Please type a name.")
    db.update_document(sb, doc_id, {"filename": name})
    st.session_state.pop("loaded_doc", None)


def do_move_doc(doc_id, course_id):
    target = st.session_state.get(f"mv_doc_{doc_id}", "none")
    db.update_document(sb, doc_id, {"module_id": None if target == "none" else target})
    st.session_state.pop("loaded_doc", None)
    st.session_state[f"mod_{course_id}"] = target  # follow the lecture to its new module
    st.session_state[f"doc_{course_id}"] = doc_id


def do_delete_doc(doc_id, course_id):
    db.delete_document(sb, doc_id)
    for key in ("loaded_doc", "active_doc"):
        st.session_state.pop(key, None)
    st.session_state.pop(f"doc_{course_id}", None)


def add_lecture(course, uploaded, module_id, has_modules):
    with st.status("Adding your lecture...", expanded=True) as status:
        st.write("📖 Reading the file")
        text, pages = extract_text(uploaded, uploaded.name)
        if len(text.strip()) < 200:
            raise ValueError("I could not find much text. This file may be mostly images or a scan.")
        st.write("💾 Saving it to your course")
        row = db.save_document(sb, course["id"], uploaded.name, pages, text, module_id)
        status.update(label="Lecture added", state="complete", expanded=False)
    # The sidebar is already drawn, so ask for the new lecture to be selected on the next run
    show_in = module_id if module_id else ("none" if has_modules else "all")
    st.session_state["_goto"] = (course["id"], show_in, row["id"])
    st.session_state["uploader_n"] = st.session_state.get("uploader_n", 0) + 1  # empty the uploader
    st.toast("Lecture added! 📚")


def load_doc(doc_id):
    """Fetch the full lecture row once, then remember it (the text can be large)."""
    cached = st.session_state.get("loaded_doc")
    if cached and cached["id"] == doc_id:
        return cached
    row = db.get_document(sb, doc_id)
    st.session_state["loaded_doc"] = row
    return row


# ---------- The Manage panel (sidebar). Only the chosen area shows. ----------
def manage_new_course():
    st.text_input("Course Name", key="new_course_name")
    st.selectbox("Course Type", list(STYLE_LABELS), format_func=STYLE_LABELS.get, key="new_course_style")
    st.button("Create Course", use_container_width=True, type="primary", on_click=act,
              args=(do_create_course,), kwargs={"done": "Course created."})


def manage_course(course):
    cid = course["id"]
    st.text_input("Course Name", value=course["name"], key=f"rn_course_{cid}")
    st.button("Rename Course", key=f"rn_course_btn_{cid}", use_container_width=True, on_click=act,
              args=(do_rename_course, cid), kwargs={"done": "Course renamed."})
    st.divider()
    ok = st.checkbox("Yes, permanently delete this course and everything in it.", key=f"cf_delcourse_{cid}")
    st.caption("This deletes its modules, lectures, guides, quizzes and revision history.")
    st.button("🗑️ Delete Course", key=f"del_course_{cid}", disabled=not ok, use_container_width=True,
              on_click=act, args=(do_delete_course, cid), kwargs={"done": "Course deleted."})


def manage_modules(course, modules, selected, module_by_id):
    cid = course["id"]
    colour_keys = list(MODULE_COLOURS)
    st.markdown("**Add a Module**")
    st.caption("A module is a section inside a course, for example Neurobiology 1. Each gets its own colour.")
    st.text_input("Module Name", key=f"new_mod_name_{cid}", placeholder="For example: Neurobiology 1")
    st.selectbox("Colour", colour_keys, index=colour_keys.index(next_free_colour(modules)),
                 format_func=colour_label, key=f"new_mod_colour_{cid}")
    st.button("Add Module", key=f"add_mod_{cid}", use_container_width=True, type="primary", on_click=act,
              args=(do_add_module, course), kwargs={"done": "Module added."})

    if selected in module_by_id:
        m = module_by_id[selected]
        mid = m["id"]
        index = [x["id"] for x in modules].index(mid)
        st.divider()
        st.markdown(f"**Edit {html.escape(m['name'])}**")
        st.text_input("Module Name", value=m["name"], key=f"rn_mod_{mid}")
        st.selectbox("Colour", colour_keys,
                     index=colour_keys.index(m["colour"]) if m["colour"] in colour_keys else 0,
                     format_func=colour_label, key=f"col_mod_{mid}")
        st.button("Save Changes", key=f"save_mod_{mid}", use_container_width=True, on_click=act,
                  args=(do_update_module, mid), kwargs={"done": "Module saved."})
        u1, u2 = st.columns(2)
        u1.button("▲ Up", key=f"up_{mid}", disabled=index == 0, use_container_width=True,
                  on_click=act, args=(do_move_module, cid, mid, -1))
        u2.button("▼ Down", key=f"down_{mid}", disabled=index == len(modules) - 1,
                  use_container_width=True, on_click=act, args=(do_move_module, cid, mid, 1))
        ok = st.checkbox("Yes, delete this module.", key=f"cf_delmod_{mid}")
        st.caption("Its lectures are kept and move to Unsorted.")
        st.button("🗑️ Delete Module", key=f"del_mod_{mid}", disabled=not ok, use_container_width=True,
                  on_click=act, args=(do_delete_module, cid, mid), kwargs={"done": "Module deleted."})
    elif modules:
        st.caption("Pick a module in the list above to rename, recolour, reorder or delete it.")


def manage_lecture(course, doc_row, modules, module_by_id):
    st.selectbox("Sort Lectures By", SORTS, key="sort_widget", on_change=remember_sort,
                 index=SORTS.index(st.session_state.get("sort_pref", SORTS[0])))
    if doc_row is None:
        st.caption("Pick a lecture in the list above to rename, move or delete it.")
        return
    did = doc_row["id"]
    st.divider()
    st.markdown(f"**Edit {html.escape(doc_row['filename'])}**")
    st.text_input("Lecture Name", value=doc_row["filename"], key=f"rn_doc_{did}")
    st.button("Rename Lecture", key=f"rn_doc_btn_{did}", use_container_width=True, on_click=act,
              args=(do_rename_doc, did), kwargs={"done": "Lecture renamed."})
    if modules:
        options = ["none"] + [m["id"] for m in modules]
        current = doc_row.get("module_id") if doc_row.get("module_id") in module_by_id else "none"
        st.selectbox(
            "Move to Module", options, index=options.index(current), key=f"mv_doc_{did}",
            format_func=lambda v: "📂 Unsorted" if v == "none"
            else f"{colour_info(module_by_id[v]['colour'])[0]} {module_by_id[v]['name']}",
        )
        st.button("Move Lecture", key=f"mv_doc_btn_{did}", use_container_width=True, on_click=act,
                  args=(do_move_doc, did, course["id"]), kwargs={"done": "Lecture moved."})
    ok = st.checkbox("Yes, permanently delete this lecture.", key=f"cf_deldoc_{did}")
    st.caption("This deletes its notes, study guide and quizzes.")
    st.button("🗑️ Delete Lecture", key=f"del_doc_{did}", disabled=not ok, use_container_width=True,
              on_click=act, args=(do_delete_doc, did, course["id"]), kwargs={"done": "Lecture deleted."})


# ---------- Notes, guides and quizzes ----------
def make_notes(doc, model):
    with st.status("Writing your quick notes...", expanded=True) as status:
        st.write("📖 Reading the lecture")
        notes, tokens_in, tokens_out = generate_notes(doc["lecture_text"], model=model)
        st.write("💾 Saving")
        db.save_notes(sb, doc["id"], notes)
        status.update(label="Quick notes ready", state="complete", expanded=False)
    doc["notes"] = notes
    st.session_state["notes_info"] = (
        f"{tokens_in} in | {tokens_out} out | about ${cost_of(model, tokens_in, tokens_out):.4f}"
    )
    st.toast("Quick notes ready! ⚡")


def make_guide(course, doc, model, opts):
    with st.status("Building your study guide...", expanded=True) as status:
        st.write("📖 Reading the lecture")
        st.write("🧠 Claude is writing (this can take a minute or two)")
        guide, tokens_in, tokens_out = generate_guide(
            doc["lecture_text"], doc["filename"], course["style"], opts, model=model
        )
        st.write("🎨 Laying it out")
        db.save_guide(sb, doc["id"], guide)
        status.update(label="Study guide ready", state="complete", expanded=False)
    doc["guide"] = guide
    st.session_state["guide_info"] = (
        f"{tokens_in} in | {tokens_out} out | about ${cost_of(model, tokens_in, tokens_out):.4f}"
    )
    st.toast("Study guide ready! 📘")


def guide_maker(course, doc):
    """The study-guide form. One click uses the defaults; the toggle lets you choose what to include."""
    defaults = GUIDE_DEFAULTS[course["style"]]
    custom = st.toggle("Choose What to Include", key=f"guide_custom_{doc['id']}")
    if not custom:
        on = [GUIDE_LABELS[k] for k, v in defaults.items() if v]
        st.caption("Includes: " + ", ".join(on) + ".")
    with st.form(f"guide_form_{doc['id']}"):
        c1, c2 = st.columns(2)
        detail = c1.selectbox("Detail Level", list(DETAIL_LEVELS), index=1)
        model_label = c2.selectbox(
            "Claude Model", list(MODEL_CHOICES),
            help="The stronger model costs about 20 times more. Best for hard material.",
        )
        picks = dict(defaults)
        if custom:
            k1, k2 = st.columns(2)
            picks["tables"] = k1.checkbox(GUIDE_LABELS["tables"], value=defaults["tables"])
            picks["charts"] = k1.checkbox(GUIDE_LABELS["charts"], value=defaults["charts"])
            picks["diagrams"] = k1.checkbox(GUIDE_LABELS["diagrams"], value=defaults["diagrams"])
            picks["examples"] = k2.checkbox(GUIDE_LABELS["examples"], value=defaults["examples"])
            picks["pearls"] = k2.checkbox(GUIDE_LABELS["pearls"], value=defaults["pearls"])
            picks["extras"] = k2.checkbox(GUIDE_LABELS["extras"] + " (Marked Purple)", value=defaults["extras"])
        submitted = st.form_submit_button("✨ Generate Study Guide", type="primary", use_container_width=True)

    if submitted:
        opts = {"detail": detail, **picks}
        if run_safely(make_guide, course, doc, MODEL_CHOICES[model_label], opts):
            st.rerun()


def render_guide_panel(course, doc, accent):
    guide = doc.get("guide")
    if guide:
        page = render_html(guide, accent)
        st.download_button(
            "⬇️ Download Study Guide", data=page, mime="text/html", type="primary",
            file_name=f"{Path(doc['filename']).stem} - Study Guide.html",
            help="Open the file in any browser. For a PDF: open it, click Print / PDF, then Save as PDF.",
        )
        if st.session_state.get("guide_info"):
            st.caption(st.session_state["guide_info"])
        components.html(page, height=780, scrolling=True)
        with st.expander("🔄 Make a New Study Guide"):
            st.caption("A new guide replaces the old one.")
            guide_maker(course, doc)
    else:
        st.markdown("#### ✨ Make a Study Guide")
        st.caption("A cheat sheet you can download and open anywhere. Usually a couple of cents on the "
                   "standard model (my estimate).")
        guide_maker(course, doc)


def quiz_name(q, filename):
    """A quiz's name. Quizzes made before names existed use the PDF's name."""
    return q.get("name") or Path(filename).stem


def quiz_labels_for(filename, saved):
    """Names for the saved-quiz picker: 'Chapter 3 Practice · 9th Nov'.
    If two quizzes share a name and day, the time is added so they can be told apart."""
    base = {q["id"]: f"{quiz_name(q, filename)} · {db.short_date(q['created_at'])}" for q in saved}
    counts = Counter(base.values())
    labels = {}
    for q in saved:
        label = base[q["id"]]
        if counts[label] > 1:
            label += f" · {db.short_time(q['created_at'])}"
        labels[q["id"]] = label
    return labels


def percent(score, total):
    return round(100 * score / total) if total else 0


def render_dashboard(attempts, by_id, filename, lecture_missed, today_iso):
    """The progress dashboard for one lecture. attempts is newest first."""
    st.subheader("📊 Progress")
    if not attempts:
        st.info("Finish a quiz and your scores, trend and weak topics will appear here.")
        return

    pcts = [percent(a["score"], a["total"]) for a in attempts]  # newest first
    latest = pcts[0]
    change = f"{latest - pcts[1]:+d}%" if len(pcts) > 1 else None
    due_now = sum(1 for m in lecture_missed if m["due_on"] <= today_iso)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Latest", f"{latest}%", delta=change)
    c2.metric("Average", f"{round(sum(pcts) / len(pcts))}%")
    c3.metric("Best", f"{max(pcts)}%")
    c4.metric("Due Today", due_now)

    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.markdown("**📈 Score Trend**")
            if len(pcts) > 1:
                st.line_chart({"Score (%)": pcts[::-1]}, height=200)  # oldest to newest
            else:
                st.caption("Take another quiz to see your trend.")
    with right:
        with st.container(border=True):
            st.markdown("**🎯 Topics to Revise**")
            counts = Counter(m["topic"] for m in lecture_missed)
            if counts:
                top = counts.most_common(5)
                biggest = top[0][1]
                for topic, number in top:
                    st.progress(number / biggest, text=f"{safe(topic)} · {number} to revise")
            else:
                st.success("No weak topics. Nice work!")

    with st.container(border=True):
        st.markdown("**🕘 Recent Attempts**")
        for a, pct in list(zip(attempts, pcts))[:5]:
            dot = "🟢" if pct >= 70 else "🟡" if pct >= 50 else "🔴"
            name = quiz_name(by_id[a["quiz_id"]], filename)
            st.progress(
                pct / 100,
                text=f"{dot} {safe(name)} · {db.short_date(a['created_at'])} · "
                     f"{a['score']} / {a['total']} ({pct}%)",
            )


def make_quiz(course, doc, model, n_questions, name):
    name = (name or "").strip()[:MAX_NAME_LENGTH] or Path(doc["filename"]).stem
    with st.status("Writing your quiz...", expanded=True) as status:
        st.write("📖 Reading the lecture")
        st.write("🧠 Claude is writing the questions")
        questions, tokens_in, tokens_out = generate_quiz(
            doc["lecture_text"],
            n_questions=n_questions,
            style_hint=STYLE_HINTS[course["style"]],
            model=model,
        )
        st.write("💾 Saving")
        row = db.save_quiz(sb, doc["id"], model, questions, name)
        status.update(label="Quiz ready", state="complete", expanded=False)
    clear_quiz()
    st.session_state["quiz"] = questions
    st.session_state["quiz_id"] = row["id"]
    st.session_state["quiz_title"] = name
    st.session_state["quiz_info"] = (
        f"{len(questions)} questions | {tokens_in} in | {tokens_out} out | "
        f"about ${cost_of(model, tokens_in, tokens_out):.4f}"
    )
    start_quiz()


def open_quiz(row, name):
    """Runs when 'Open' is clicked: load a saved quiz (free, no Claude)."""
    clear_quiz()
    st.session_state["quiz"] = row["questions"]
    st.session_state["quiz_id"] = row["id"]
    st.session_state["quiz_title"] = name
    start_quiz()


def reshuffled(q):
    """A copy of a question with its options in a new order, so you can't just remember the position."""
    correct_text = q["options"][q["correct_index"]]
    options = q["options"][:]
    random.shuffle(options)
    return {**q, "options": options, "correct_index": options.index(correct_text)}


def start_revision(candidates):
    """Runs when a revision button is clicked: replay up to REVISION_SIZE questions (free)."""
    chosen = sorted(candidates, key=lambda m: -m["times_wrong"])[:REVISION_SIZE]
    questions = [reshuffled(m["question"]) for m in chosen]
    random.shuffle(questions)
    clear_quiz()
    st.session_state["quiz"] = questions
    st.session_state["quiz_id"] = None  # a revision round is not a saved quiz
    st.session_state["quiz_title"] = "🔁 Revision Round"
    start_quiz()


def start_mixed(course_id):
    """Mixed practice: a random mix of questions from every saved quiz in the course (free)."""
    flagged = db.list_flagged_keys(sb, course_id)
    pool = [q for q in db.list_course_questions(sb, course_id)
            if db.question_key(q["question"]) not in flagged]
    if len(pool) < 4:
        raise ValueError("Make a few quizzes in this course first, then come back for mixed practice.")
    questions = [reshuffled(q) for q in random.sample(pool, min(REVISION_SIZE, len(pool)))]
    clear_quiz()
    st.session_state["quiz"] = questions
    st.session_state["quiz_id"] = None
    st.session_state["quiz_title"] = "🔀 Mixed Practice"
    start_quiz()


def flag_question(course_id, q):
    """Runs when 'Report' is clicked. Returns True if it was saved."""
    try:
        db.flag_question(sb, course_id, q)
        st.toast("Thanks, reported. It won't come back in revision or mixed practice.")
        return True
    except Exception as error:
        print("Flagging failed:", error)
        st.toast("Could not save that report. Please try again.")
        return False


def save_result(course_id, quiz):
    """Save the score (normal quizzes) and update the missed-questions list (all quizzes)."""
    answers = st.session_state["quiz_answers"]
    wrong = st.session_state.get("wrong_answers", [])
    quiz_id = st.session_state.get("quiz_id")
    if quiz_id:
        db.save_attempt(sb, quiz_id, len(quiz) - len(wrong), len(quiz), wrong)
    db.record_results(sb, course_id, quiz, answers)


# =====================================================================
# SIDEBAR: the navigator (course > modules > lectures) plus one Manage box
# =====================================================================
courses = db.list_courses(sb)
course = None
modules, module_by_id, docs = [], {}, []
selected = "all"
doc_id = None

with st.sidebar:
    st.divider()
    if courses:
        st.markdown("##### 📚 Course")
        names = {c["id"]: c["name"] for c in courses}
        st.selectbox("Course", list(names), format_func=names.get, key="course_id",
                     label_visibility="collapsed")
        course = next(c for c in courses if c["id"] == st.session_state["course_id"])

        modules = db.list_modules(sb, course["id"])
        module_by_id = {m["id"]: m for m in modules}
        docs = db.list_documents(sb, course["id"])
        mod_key = f"mod_{course['id']}"
        doc_key = f"doc_{course['id']}"

        # After an upload, jump to the new lecture
        goto = st.session_state.pop("_goto", None)
        if goto and goto[0] == course["id"]:
            st.session_state[mod_key] = goto[1]
            st.session_state[doc_key] = goto[2]

        unsorted_count = sum(1 for d in docs if d["module_id"] not in module_by_id)
        options = ["all"] + [m["id"] for m in modules] + (["none"] if modules and unsorted_count else [])
        if st.session_state.get(mod_key, "all") not in options:
            st.session_state[mod_key] = "all"

        if modules:
            st.markdown("##### 🗂️ Modules")
            selected = st.radio(
                "Module", options, key=mod_key, label_visibility="collapsed",
                format_func=lambda v: module_label(v, docs, module_by_id, unsorted_count),
            )

        if selected == "all":
            shown = docs
        elif selected == "none":
            shown = [d for d in docs if d["module_id"] not in module_by_id]
        else:
            shown = [d for d in docs if d["module_id"] == selected]

        st.markdown("##### 📄 Lectures")
        if shown:
            ordered = sort_docs(shown, st.session_state.get("sort_pref", SORTS[0]))
            labels = {d["id"]: doc_label(d, module_by_id, selected) for d in ordered}
            if st.session_state.get(doc_key) not in labels:
                st.session_state.pop(doc_key, None)  # the chosen lecture is not in this module
            doc_id = st.radio("Lecture", list(labels), format_func=labels.get, key=doc_key,
                              label_visibility="collapsed")
        else:
            st.caption("No lectures here yet. Add one from the main page.")

        st.divider()

    with st.expander("⚙️ Manage", expanded=not courses):
        if not courses:
            st.caption("Create your first course to get started.")
            manage_new_course()
        else:
            areas = ["course", "modules", "lecture", "new"]
            area_labels = {"course": "✏️ This Course", "modules": "🗂️ Modules",
                           "lecture": "📄 Lectures", "new": "➕ New Course"}
            area = st.selectbox("What would you like to change?", areas, format_func=area_labels.get,
                                key="manage_area")
            st.divider()
            if area == "course":
                manage_course(course)
            elif area == "modules":
                manage_modules(course, modules, selected, module_by_id)
            elif area == "lecture":
                manage_lecture(course, next((d for d in docs if d["id"] == doc_id), None), modules, module_by_id)
            else:
                manage_new_course()

# =====================================================================
# MAIN PAGE: upload, notes, quizzes
# =====================================================================
if not courses:
    st.title("📚 StudyBuddy")
    st.info("Create your first course in the sidebar to get started.")
    st.stop()

doc = load_doc(doc_id) if doc_id else None
lecture_module = module_by_id.get(doc.get("module_id")) if doc else module_by_id.get(selected)
accent = colour_info(lecture_module["colour"])[1] if lecture_module else STYLE_ACCENTS[course["style"]]

# Clicking a different course, module or lecture closes any open quiz
nav_sig = (course["id"], selected, doc_id)
if st.session_state.get("nav_sig") != nav_sig:
    if "nav_sig" in st.session_state and "quiz" in st.session_state:
        clear_quiz()
    st.session_state["nav_sig"] = nav_sig

if st.session_state.get("active_doc") != doc_id:
    st.session_state.pop("notes_info", None)
    st.session_state.pop("guide_info", None)
    st.session_state["active_doc"] = doc_id

crumbs = []
if selected in module_by_id:
    crumbs.append(f"{colour_info(module_by_id[selected]['colour'])[0]} {module_by_id[selected]['name']}")
elif selected == "none":
    crumbs.append("📂 Unsorted")
if doc:
    crumbs.append(doc["filename"])
hero(course["name"], STYLE_LABELS[course["style"]] + " Course", crumbs or ["All lectures"], accent)

# ---------- An open quiz takes over the page ----------
if "quiz" in st.session_state:
    quiz = st.session_state["quiz"]
    if st.session_state.get("quiz_title"):
        st.subheader(st.session_state["quiz_title"])
    render_quiz(quiz, on_flag=lambda q: flag_question(course["id"], q))

    in_progress = st.session_state["quiz_index"] < len(quiz)

    # Save the result once, the first time the results screen appears
    if not in_progress and not st.session_state.get("attempt_saved"):
        if run_safely(save_result, course["id"], quiz):
            st.session_state["attempt_saved"] = True

    if st.session_state.get("quiz_info"):
        st.caption(st.session_state["quiz_info"])
    if in_progress:
        st.button("✕ Exit Quiz", on_click=clear_quiz)
    st.stop()

# ---------- Add a lecture ----------
with st.expander("⬆️ Add a Lecture", expanded=not docs or doc is None):
    target_module = None
    if modules:
        if selected in module_by_id:
            target_module = selected
            where = f"{colour_info(module_by_id[selected]['colour'])[0]} {safe(module_by_id[selected]['name'])}"
        else:
            where = "📂 Unsorted"
        st.caption(f"This lecture will be added to: **{where}**. "
                   "To file it in a module, pick that module in the sidebar first.")
    uploaded = st.file_uploader(
        "PDF or PowerPoint", type=["pdf", "pptx"],
        key=f"uploader_{st.session_state.get('uploader_n', 0)}",
    )
    if uploaded is not None:
        if uploaded.size > MAX_MB * 1024 * 1024:
            st.error(f"That file is over {MAX_MB} MB. Please choose a smaller one.")
        elif any(d["filename"] == uploaded.name for d in docs):
            st.warning("A lecture with this file name is already in this course.")
        elif st.button("Save Lecture to This Course", type="primary"):
            if run_safely(add_lecture, course, uploaded, target_module, bool(modules)):
                st.rerun()

if doc is None:
    if docs:
        st.info("No lectures here yet. Add one above, or pick another module in the sidebar.")
    else:
        st.info("No lectures in this course yet. Add one above.")
    st.stop()

# ---------- Data shared by the tabs (fetched once per click) ----------
saved = db.list_quizzes(sb, doc_id)
by_id = {q["id"]: q for q in saved}
flagged = db.list_flagged_keys(sb, course["id"])
missed = [m for m in db.list_missed(sb, course["id"]) if m["question_key"] not in flagged]
today = db.today().isoformat()
due = [m for m in missed if m["due_on"] <= today]

tab_notes, tab_quiz, tab_revise = st.tabs(["📝 Notes", "❓ Quiz", "🔁 Revise & Practise"])

# ---------- Notes ----------
with tab_notes:
    mode = st.radio("Notes Type", ["📘 Study Guide", "⚡ Quick Notes"], horizontal=True,
                    label_visibility="collapsed", key=f"notes_mode_{doc_id}")
    if mode.startswith("📘"):
        render_guide_panel(course, doc, accent)
    elif doc["notes"]:
        render_notes(doc["notes"])
        if st.session_state.get("notes_info"):
            st.caption(st.session_state["notes_info"])
        st.caption("These notes are a first draft. Check numbers against your original slides.")
    else:
        st.caption("Short in-app notes for a quick glance. For a full downloadable guide, use Study Guide.")
        if st.button("⚡ Make Quick Notes", type="primary"):
            if run_safely(make_notes, doc, MODEL_CHEAP):
                st.rerun()

# ---------- Quiz ----------
with tab_quiz:
    st.subheader("New Quiz")
    with st.form("new_quiz_form"):
        name_box = f"quiz_name_{doc_id}_{st.session_state.get('quiz_name_n', 0)}"
        new_quiz_name = st.text_input(
            "Quiz Name", key=name_box, max_chars=MAX_NAME_LENGTH,
            placeholder="For example: Chapter 3 Practice (blank uses the PDF's name)",
        )
        q1, q2 = st.columns(2)
        n_questions = q1.slider("Number of Questions", 4, 12, 8)
        model_label = q2.selectbox(
            "Claude Model", list(MODEL_CHOICES),
            help="The stronger model costs about 20 times more. Best for hard material such as calculations.",
        )
        make_clicked = st.form_submit_button("❓ Make Quiz", type="primary", use_container_width=True)

    if make_clicked:
        if run_safely(make_quiz, course, doc, MODEL_CHOICES[model_label], n_questions, new_quiz_name):
            st.session_state["quiz_name_n"] = st.session_state.get("quiz_name_n", 0) + 1  # empty the name box
            st.rerun()

    if saved:
        st.divider()
        st.subheader("Saved Quizzes")
        quiz_labels = quiz_labels_for(doc["filename"], saved)
        s1, s2 = st.columns([4, 1], vertical_alignment="bottom")
        chosen = s1.selectbox("Choose a Quiz", list(quiz_labels), format_func=quiz_labels.get,
                              key=f"saved_quiz_{doc_id}", label_visibility="collapsed")
        s2.button("Open", key=f"open_quiz_{doc_id}", on_click=open_quiz, type="primary",
                  args=(by_id[chosen], quiz_name(by_id[chosen], doc["filename"])), use_container_width=True)

    # The dashboard: this lecture's attempts (newest first) and its open mistakes
    st.divider()
    attempts = [a for a in db.recent_attempts(sb) if a["quiz_id"] in by_id][:50]
    lecture_keys = {db.question_key(q["question"]) for row in saved for q in row["questions"]}
    lecture_missed = [m for m in missed if m["question_key"] in lecture_keys]
    render_dashboard(attempts, by_id, doc["filename"], lecture_missed, today)

# ---------- Revise & Practise (whole course) ----------
with tab_revise:
    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.markdown("#### 🔁 Spaced Revision")
            m1, m2 = st.columns(2)
            m1.metric("Due Today", len(due))
            m2.metric("Later", len(missed) - len(due))
            if not missed:
                st.caption("Nothing yet. Questions you miss in quizzes collect here.")
            elif due:
                topics = [t for t, _ in Counter(m["topic"] for m in due).most_common(3)]
                st.caption("Topics: " + ", ".join(safe(t) for t in topics))
                st.button("Start Revision", key="start_rev", on_click=start_revision, args=(due,),
                          type="primary", use_container_width=True)
            else:
                st.caption(f"Nothing due today. Next review: {db.short_date(min(m['due_on'] for m in missed))}.")
                st.button("Practise Early", key="practise_early", on_click=start_revision, args=(missed,),
                          use_container_width=True)
    with right:
        with st.container(border=True):
            st.markdown("#### 🔀 Mixed Practice")
            st.caption(f"A random mix of up to {REVISION_SIZE} questions from every saved quiz in this course.")
            if st.button("Start Mixed Practice", key="start_mixed", use_container_width=True):
                if run_safely(start_mixed, course["id"]):
                    st.rerun()

    with st.expander("ℹ️ How This Works"):
        st.markdown(
            f"- Revision covers every lecture in the course and replays up to {REVISION_SIZE} questions.\n"
            "- A missed question is due straight away. Answer it correctly when it is due and it returns "
            "after 1 day, then 3 days, then counts as mastered. A wrong answer starts it over.\n"
            "- Practising early does not count towards mastering a question, but mistakes are still recorded.\n"
            "- Revision and mixed practice are free (no Claude call)."
        )
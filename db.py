#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
db.py - everything that talks to the Supabase database.
"""
import hashlib
from datetime import datetime, timedelta, timezone

# Singapore time (UTC+8, no daylight saving), so "today" matches your day
SGT = timezone(timedelta(hours=8))

# Spaced revision: after the 1st correct answer a question waits 1 day, after the
# 2nd it waits 3 days, and the 3rd correct answer counts as mastered.
SPACING_DAYS = {1: 1, 2: 3}
MASTER_AFTER = 3


def today():
    """Today's date in Singapore."""
    return datetime.now(SGT).date()


def to_sgt(text):
    """Turn a timestamp from the database into a datetime in Singapore time."""
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(SGT)


def short_date(text):
    """'2026-11-09T08:12:03+00:00' or '2026-11-09' becomes '9th Nov'."""
    try:
        d = datetime.fromisoformat(text) if len(text) == 10 else to_sgt(text)
    except ValueError:
        return text[:10]
    day = d.day
    suffix = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix} {d.strftime('%b')}"


def short_time(text):
    """'2026-11-09T08:12:03+00:00' becomes '4:12 PM' (Singapore time)."""
    try:
        return to_sgt(text).strftime("%-I:%M %p")
    except ValueError:
        return ""


def _deleted(result, what):
    """A delete that removed nothing means it was blocked, so say so."""
    if not result.data:
        raise ValueError(f"Could not delete the {what}. Nothing was removed.")


# ---------- Courses ----------
def list_courses(sb):
    return sb.table("courses").select("*").order("created_at").execute().data


def add_course(sb, name, style):
    return sb.table("courses").insert({"name": name, "style": style}).execute().data[0]


def rename_course(sb, course_id, name):
    name = (name or "").strip()
    if not name:
        raise ValueError("Please type a name.")
    sb.table("courses").update({"name": name}).eq("id", course_id).execute()


def delete_course(sb, course_id):
    _deleted(sb.table("courses").delete().eq("id", course_id).execute(), "course")


# ---------- Modules ----------
def list_modules(sb, course_id):
    return (
        sb.table("modules").select("*").eq("course_id", course_id)
        .order("position").order("created_at").execute().data
    )


def add_module(sb, course_id, name, colour, position):
    row = {"course_id": course_id, "name": name.strip(), "colour": colour, "position": position}
    return sb.table("modules").insert(row).execute().data[0]


def update_module(sb, module_id, changes):
    sb.table("modules").update(changes).eq("id", module_id).execute()


def delete_module(sb, module_id):
    # Lectures inside are kept: the database sets their module to empty (Unsorted).
    _deleted(sb.table("modules").delete().eq("id", module_id).execute(), "module")


def swap_modules(sb, a, b):
    """Swap the order positions of two modules."""
    sb.table("modules").update({"position": b["position"]}).eq("id", a["id"]).execute()
    sb.table("modules").update({"position": a["position"]}).eq("id", b["id"]).execute()


# ---------- Lectures ----------
def list_documents(sb, course_id):
    return (
        sb.table("documents")
        .select("id, filename, pages, created_at, module_id")
        .eq("course_id", course_id)
        .order("created_at", desc=True)
        .execute()
        .data
    )


def get_document(sb, doc_id):
    return sb.table("documents").select("*").eq("id", doc_id).execute().data[0]


def save_document(sb, course_id, filename, pages, text, module_id=None):
    row = {"course_id": course_id, "filename": filename, "pages": pages, "lecture_text": text}
    if module_id:
        row["module_id"] = module_id
    return sb.table("documents").insert(row).execute().data[0]


def update_document(sb, doc_id, changes):
    sb.table("documents").update(changes).eq("id", doc_id).execute()


def delete_document(sb, doc_id):
    _deleted(sb.table("documents").delete().eq("id", doc_id).execute(), "lecture")


def save_notes(sb, doc_id, notes):
    sb.table("documents").update({"notes": notes}).eq("id", doc_id).execute()


def save_guide(sb, doc_id, guide):
    sb.table("documents").update({"guide": guide}).eq("id", doc_id).execute()


# ---------- Quizzes ----------
def list_quizzes(sb, doc_id):
    return (
        sb.table("quizzes")
        .select("id, created_at, model, name, questions")
        .eq("document_id", doc_id)
        .order("created_at", desc=True)
        .execute()
        .data
    )


def save_quiz(sb, doc_id, model, questions, name):
    row = {"document_id": doc_id, "model": model, "questions": questions, "name": name}
    return sb.table("quizzes").insert(row).execute().data[0]


def save_attempt(sb, quiz_id, score, total, wrong):
    row = {"quiz_id": quiz_id, "score": score, "total": total, "wrong": wrong}
    sb.table("attempts").insert(row).execute()


def recent_attempts(sb):
    return (
        sb.table("attempts")
        .select("quiz_id, score, total, created_at")
        .order("created_at", desc=True)
        .limit(50)
        .execute()
        .data
    )


# ---------- Revision ----------
def question_key(text):
    """A short fingerprint of a question, so the same question is recognised next time."""
    return hashlib.md5(text.strip().lower().encode("utf-8")).hexdigest()


def list_missed(sb, course_id):
    """Questions in this course that the person got wrong and has not mastered yet."""
    return (
        sb.table("missed_questions").select("*")
        .eq("course_id", course_id).eq("mastered", False)
        .execute().data
    )


def record_results(sb, course_id, questions, answers):
    """After a quiz: save new mistakes and move old ones along the spaced-revision schedule."""
    keyed = {}
    for i, q in enumerate(questions):
        keyed[question_key(q["question"])] = (q, answers.get(i) == q["correct_index"])

    existing = (
        sb.table("missed_questions")
        .select("id, question_key, times_wrong, mastered, box, due_on")
        .eq("course_id", course_id).in_("question_key", list(keyed))
        .execute().data
    )
    by_key = {r["question_key"]: r for r in existing}
    now = today()

    for key, (q, was_right) in keyed.items():
        row = by_key.get(key)
        if was_right:
            # A correct answer only counts if the question was due. This stops
            # you "mastering" a question by repeating it several times in one sitting.
            if row and not row["mastered"] and row["due_on"] <= now.isoformat():
                box = row["box"] + 1
                if box >= MASTER_AFTER:
                    change = {"mastered": True, "box": box}
                else:
                    wait = timedelta(days=SPACING_DAYS[box])
                    change = {"box": box, "due_on": (now + wait).isoformat()}
                sb.table("missed_questions").update(change).eq("id", row["id"]).execute()
        elif row:
            # Wrong again: start over, and it is due straight away
            sb.table("missed_questions").update(
                {"mastered": False, "times_wrong": row["times_wrong"] + 1, "question": q,
                 "box": 0, "due_on": now.isoformat()}
            ).eq("id", row["id"]).execute()
        else:
            sb.table("missed_questions").insert(
                {"course_id": course_id, "question_key": key, "topic": q["topic"], "question": q,
                 "box": 0, "due_on": now.isoformat()}
            ).execute()


def list_course_questions(sb, course_id):
    """Every question from every saved quiz in this course, with duplicates removed."""
    ids = [d["id"] for d in list_documents(sb, course_id)]
    if not ids:
        return []
    rows = sb.table("quizzes").select("questions").in_("document_id", ids).execute().data
    seen = set()
    found = []
    for row in rows:
        for q in row["questions"]:
            key = question_key(q["question"])
            if key not in seen:
                seen.add(key)
                found.append(q)
    return found


def flag_question(sb, course_id, q):
    """Report a question as wrong or unclear, so it stops coming back."""
    row = {"course_id": course_id, "question_key": question_key(q["question"]), "question": q}
    try:
        sb.table("flagged_questions").insert(row).execute()
    except Exception as error:
        # Reporting the same question twice is fine. Anything else is a real problem.
        if "duplicate" not in str(error).lower() and "23505" not in str(error):
            raise


def list_flagged_keys(sb, course_id):
    """The fingerprints of every question this person has reported in this course."""
    rows = (
        sb.table("flagged_questions").select("question_key")
        .eq("course_id", course_id).execute().data
    )
    return {r["question_key"] for r in rows}
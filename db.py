#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Nov  9 15:24:28 2026

@author: louis
"""
import hashlib
def list_courses(sb):
    return sb.table("courses").select("*").order("created_at").execute().data


def add_course(sb, name, style):
    return sb.table("courses").insert({"name": name, "style": style}).execute().data[0]


def list_documents(sb, course_id):
    return (
        sb.table("documents")
        .select("id, filename, pages, created_at")
        .eq("course_id", course_id)
        .order("created_at", desc=True)
        .execute()
        .data
    )


def get_document(sb, doc_id):
    return sb.table("documents").select("*").eq("id", doc_id).execute().data[0]


def save_document(sb, course_id, filename, pages, text):
    row = {"course_id": course_id, "filename": filename, "pages": pages, "lecture_text": text}
    return sb.table("documents").insert(row).execute().data[0]


def save_notes(sb, doc_id, notes):
    sb.table("documents").update({"notes": notes}).eq("id", doc_id).execute()


def list_quizzes(sb, doc_id):
    return (
        sb.table("quizzes")
        .select("id, created_at, model, questions")
        .eq("document_id", doc_id)
        .order("created_at", desc=True)
        .execute()
        .data
    )


def save_quiz(sb, doc_id, model, questions):
    row = {"document_id": doc_id, "model": model, "questions": questions}
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
    """After a quiz: save new mistakes, and mark old mistakes as mastered if now answered correctly."""
    keyed = {}
    for i, q in enumerate(questions):
        keyed[question_key(q["question"])] = (q, answers.get(i) == q["correct_index"])

    existing = (
        sb.table("missed_questions").select("id, question_key, times_wrong, mastered")
        .eq("course_id", course_id).in_("question_key", list(keyed))
        .execute().data
    )
    by_key = {r["question_key"]: r for r in existing}

    for key, (q, was_right) in keyed.items():
        row = by_key.get(key)
        if was_right:
            if row and not row["mastered"]:
                sb.table("missed_questions").update({"mastered": True}).eq("id", row["id"]).execute()
        elif row:
            sb.table("missed_questions").update(
                {"mastered": False, "times_wrong": row["times_wrong"] + 1, "question": q}
            ).eq("id", row["id"]).execute()
        else:
            sb.table("missed_questions").insert(
                {"course_id": course_id, "question_key": key, "topic": q["topic"], "question": q}
            ).execute()
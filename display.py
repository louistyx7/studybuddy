#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
display.py - draws the notes on the page (dark-mode friendly).
"""

import streamlit as st

# Colours for the key-concept titles (Streamlit knows these names)
COLOURS = ["blue", "green", "orange", "violet", "red"]

# Colours that make Claude's diagrams readable on a dark background
DIAGRAM_STYLE = (
    'bgcolor="transparent"; '
    'node [style=filled, fillcolor="#1A2625", color="#2DD4BF", fontcolor="#E5E7EB"]; '
    'edge [color="#2DD4BF", fontcolor="#E5E7EB"]; '
)


def safe(text):
    """Stop dollar signs being treated as maths formatting (matters for finance notes)."""
    return str(text).replace("$", "\\$")


def style_diagram(dot):
    """Add our dark-mode colours right after the first { in the diagram code."""
    brace = dot.find("{")
    if brace == -1:
        return dot
    return dot[: brace + 1] + " " + DIAGRAM_STYLE + dot[brace + 1:]


def render_notes(notes):
    """Draw one set of structured notes on the page."""

    if notes.get("missing_content_note"):
        st.warning("**Heads up:** " + safe(notes["missing_content_note"]))

    tab_overview, tab_concepts, tab_terms, tab_summary = st.tabs(
        ["📖 Overview", "💡 Key Concepts", "🔤 Terms", "✅ Summary"]
    )

    with tab_overview:
        st.info(safe(notes["overview"]))
        diagram = notes.get("diagram", "").strip()
        if diagram:
            st.graphviz_chart(style_diagram(diagram))

    with tab_concepts:
        for number, item in enumerate(notes["key_concepts"], start=1):
            colour = COLOURS[(number - 1) % len(COLOURS)]
            with st.container(border=True):
                st.markdown(f":{colour}[**{number}. {safe(item['title'])}**]")
                st.write(safe(item["explanation"]))

    with tab_terms:
        left, right = st.columns(2)
        for i, item in enumerate(notes["important_terms"]):
            with (left if i % 2 == 0 else right):
                with st.container(border=True):
                    st.markdown(f"**{safe(item['term'])}**")
                    st.write(safe(item["definition"]))

    with tab_summary:
        st.success(safe(notes["summary"]))
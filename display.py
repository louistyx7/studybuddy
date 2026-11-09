#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Nov  9 13:14:49 2026

@author: louis
"""

import streamlit as st

# Colours for the key-concept titles (Streamlit knows these names)
COLOURS = ["blue", "green", "orange", "violet", "red"]


def safe(text):
    """Stop dollar signs being treated as maths formatting (matters for finance notes)."""
    return str(text).replace("$", "\\$")


def render_notes(notes):
    """Draw one set of structured notes on the page."""

    # Warning box for anything Claude says is missing
    if notes.get("missing_content_note"):
        st.warning("**Heads up:** " + safe(notes["missing_content_note"]))

    tab_overview, tab_concepts, tab_terms, tab_summary = st.tabs(
        ["📖 Overview", "💡 Key concepts", "🔤 Terms", "✅ Summary"]
    )

    with tab_overview:
        st.info(safe(notes["overview"]))
        diagram = notes.get("diagram", "").strip()
        if diagram:
            st.graphviz_chart(diagram)

    with tab_concepts:
        for number, item in enumerate(notes["key_concepts"]):
            colour = COLOURS[number % len(COLOURS)]
            with st.container(border=True):
                st.markdown(f":{colour}[**{safe(item['title'])}**]")
                st.write(safe(item["explanation"]))

    with tab_terms:
        for item in notes["important_terms"]:
            st.markdown(f"**{safe(item['term'])}**: {safe(item['definition'])}")

    with tab_summary:
        st.success(safe(notes["summary"]))
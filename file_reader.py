#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Nov  9 13:17:13 2026

@author: louis
"""

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from pdf_reader import extract_pdf_text

# The most slides we allow in one file (keeps costs tiny)
MAX_SLIDES = 60


def _shape_text(shape):
    """Return the text lines found inside one shape on a slide."""
    lines = []
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        # A group is a bundle of shapes, so look inside it
        for inner in shape.shapes:
            lines.extend(_shape_text(inner))
    elif shape.has_text_frame:
        text = shape.text_frame.text.strip()
        if text:
            lines.append(text)
    elif shape.has_table:
        for row in shape.table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            lines.append(" | ".join(cells))
    elif shape.has_chart:
        # Real PowerPoint charts keep their numbers as data, so we can read them
        try:
            lines.append("Chart data:")
            for plot in shape.chart.plots:
                categories = [str(c) for c in plot.categories]
                for series in plot.series:
                    values = list(series.values)
                    pairs = ", ".join(f"{c} = {v}" for c, v in zip(categories, values))
                    lines.append(f"  {series.name}: {pairs}")
        except Exception:
            lines.append("(a chart was here but its data could not be read)")
    return lines


def extract_pptx_text(file):
    """Open a PowerPoint and return (all its text, number of slides)."""
    presentation = Presentation(file)
    total_slides = len(presentation.slides)

    if total_slides > MAX_SLIDES:
        raise ValueError(f"This deck has {total_slides} slides. The limit is {MAX_SLIDES}.")

    parts = []
    for number, slide in enumerate(presentation.slides, start=1):
        lines = []
        for shape in slide.shapes:
            lines.extend(_shape_text(shape))

        # Speaker notes, if the slide has any
        if slide.has_notes_slide:
            frame = slide.notes_slide.notes_text_frame
            if frame is not None and frame.text.strip():
                lines.append("Speaker notes: " + frame.text.strip())

        parts.append(f"--- Slide {number} ---\n" + "\n".join(lines))

    return "\n\n".join(parts), total_slides


def extract_text(file, filename):
    """Pick the right reader for the file type. Returns (text, page or slide count)."""
    name = filename.lower()
    if name.endswith(".pdf"):
        return extract_pdf_text(file)
    if name.endswith(".pptx"):
        return extract_pptx_text(file)
    raise ValueError(
        "Only .pdf and .pptx files are supported. "
        "For an old .ppt file, open it in PowerPoint and save it as .pptx."
    )
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Nov  9 13:01:22 2026

@author: louis
"""

from pypdf import PdfReader

# The most pages we allow in one file (keeps costs tiny)
MAX_PAGES = 60


def extract_pdf_text(path):
    """Open a PDF and return (all its text, number of pages)."""
    reader = PdfReader(path)
    total_pages = len(reader.pages)

    if total_pages > MAX_PAGES:
        raise ValueError(f"PDF has {total_pages} pages. The limit is {MAX_PAGES}.")

    parts = []
    for number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        parts.append(f"--- Page {number} ---\n{text}")

    return "\n\n".join(parts), total_pages


# This block only runs when we run this file directly (a quick self-test)
if __name__ == "__main__":
    text, pages = extract_pdf_text("sample.pdf")
    print("Pages:", pages)
    print("Characters:", len(text))
    print("Rough tokens:", len(text) // 4)
    print()
    print("First 500 characters:")
    print(text[:500])
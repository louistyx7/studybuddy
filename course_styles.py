#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Nov  9 15:31:18 2026

@author: louis
"""

STYLE_HINTS = {
    "general": "",
    "finance": (
        "Finance and banking. Mix conceptual questions with calculation questions. "
        "About a third of the questions should need a short calculation that uses formulas "
        "or numbers that appear in the lecture (for example returns, present value, yields, ratios). "
        "Put every number the student needs inside the question. "
        "Wrong options must be the results of typical mistakes (wrong formula, forgetting to "
        "annualise, sign errors, mixing up percentages and decimals). "
        "In the explanation, show the working step by step. "
        "Never use a formula that is not in the lecture."
    ),
    "physio": (
        "Physiotherapy. Mix clinical reasoning with anatomy and physiology. "
        "About half of the questions should be a short patient vignette (age, presentation, "
        "relevant findings) asking for the most likely structure involved, the most relevant "
        "assessment finding, or the best next step, based only on what the lecture says. "
        "The rest test anatomy and physiology: muscle actions, innervation, joint movements, "
        "landmarks and mechanisms. Wrong options must be plausible alternatives a student could "
        "confuse. Do not give clinical advice beyond what the lecture states."
    ),
}
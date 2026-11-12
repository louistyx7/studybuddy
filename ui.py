#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Nov 12 21:47:33 2026

@author: louis
"""

"""ui.py - the look and feel: animations, the page header and quiz answer feedback."""

import html

import streamlit as st

CSS = """<style>
@keyframes sb-fade-up{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
@keyframes sb-fade{from{opacity:0}to{opacity:1}}
@keyframes sb-pop{0%{transform:scale(.95)}50%{transform:scale(1.035)}100%{transform:scale(1)}}
@keyframes sb-shake{0%,100%{transform:translateX(0)}20%{transform:translateX(-7px)}40%{transform:translateX(7px)}60%{transform:translateX(-4px)}80%{transform:translateX(4px)}}
.stApp{animation:sb-fade .4s ease both}
footer{visibility:hidden}
[data-testid="stSidebar"] h5{margin:.2rem 0 .3rem;letter-spacing:.02em}
[data-baseweb="tab-panel"]{animation:sb-fade-up .35s ease both}
[data-testid="stAlert"]{border-radius:12px;animation:sb-fade-up .3s ease both}
[data-testid="stMetric"]{padding:10px 14px;border-radius:12px;background:rgba(128,128,128,.09);animation:sb-fade-up .4s ease both}
[data-testid="stExpander"]{border-radius:12px;transition:border-color .2s ease,box-shadow .2s ease}
[data-testid="stExpander"]:hover{border-color:rgba(45,212,191,.55);box-shadow:0 2px 14px rgba(0,0,0,.22)}
iframe{border-radius:12px;animation:sb-fade .5s ease both}
[data-testid="stProgress"] div{transition:width .6s ease}
.stButton>button,.stDownloadButton>button,[data-testid="stFormSubmitButton"]>button{border-radius:10px;transition:transform .15s ease,box-shadow .2s ease,border-color .2s ease,filter .2s ease}
.stButton>button:hover,.stDownloadButton>button:hover,[data-testid="stFormSubmitButton"]>button:hover{transform:translateY(-1px);box-shadow:0 5px 16px rgba(0,0,0,.3);filter:brightness(1.07)}
.stButton>button:active,.stDownloadButton>button:active,[data-testid="stFormSubmitButton"]>button:active{transform:scale(.97)}
[data-testid="stSidebar"] [data-testid="stRadio"] label{padding:6px 10px;border-radius:8px;transition:background-color .2s ease,transform .2s ease}
[data-testid="stSidebar"] [data-testid="stRadio"] label:hover{background:rgba(128,128,128,.15);transform:translateX(3px)}
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked){background:rgba(45,212,191,.17)}
.sb-hero{padding:18px 22px;border-radius:14px;margin-bottom:10px;animation:sb-fade-up .45s ease both}
.sb-title{font-size:2rem;font-weight:800;line-height:1.2}
.sb-meta{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-top:8px;opacity:.95}
.sb-badge{color:#fff;font-size:.72rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;padding:3px 10px;border-radius:99px}
.sb-crumbs{font-size:.92rem}
.sb-sep{opacity:.5;margin:0 4px}
[class*="st-key-qcard"]{animation:sb-fade-up .35s ease both}
.sb-score{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;animation:sb-pop .6s ease both;margin:4px 0 8px}
.sb-score-num{font-size:3.4rem;font-weight:800;color:#2DD4BF;line-height:1}
.sb-score-of{font-size:1.6rem;opacity:.75}
.sb-score-pct{font-size:1.1rem;font-weight:700;padding:3px 12px;border-radius:99px;background:rgba(45,212,191,.18)}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style>"""


def inject_css():
    """Add the animations and polish to the page."""
    st.markdown(CSS, unsafe_allow_html=True)


def hero(title, badge, crumbs, accent):
    """One header card: course name, course-type badge and a breadcrumb. accent is a #RRGGBB colour."""
    crumb_html = '<span class="sb-sep">›</span>'.join(html.escape(c) for c in crumbs)
    st.markdown(
        f'<div class="sb-hero" style="border-left:6px solid {accent};'
        f'background:linear-gradient(120deg,{accent}38,{accent}0a)">'
        f'<div class="sb-title">📚 {html.escape(title)}</div>'
        f'<div class="sb-meta"><span class="sb-badge" style="background:{accent}">{html.escape(badge)}</span>'
        f'<span class="sb-crumbs">{crumb_html}</span></div></div>',
        unsafe_allow_html=True,
    )


def quiz_css(index, correct=None, picked=None):
    """Animations for one question's answer buttons. After answering, the right one pops green
    and a wrong pick shakes red."""
    rules = []
    for j in range(4):
        rules.append(
            f".st-key-q{index}_option{j}{{animation:sb-fade-up .35s ease both;animation-delay:{j * 0.07:.2f}s}}"
        )
    if correct is not None:
        rules.append(
            f".st-key-q{index}_option{correct} button{{opacity:1!important;border-color:#22c55e!important;"
            f"background:rgba(34,197,94,.17)!important;animation:sb-pop .45s ease}}"
        )
        if picked is not None and picked != correct:
            rules.append(
                f".st-key-q{index}_option{picked} button{{opacity:1!important;border-color:#ef4444!important;"
                f"background:rgba(239,68,68,.15)!important;animation:sb-shake .45s ease}}"
            )
    return "<style>" + "".join(rules) + "</style>"
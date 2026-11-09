#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Nov  9 15:24:12 2026

@author: louis
"""

import os

import streamlit as st
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()


def get_client():
    """One Supabase connection PER browser session (never shared between people)."""
    if "sb" not in st.session_state:
        st.session_state["sb"] = create_client(
            os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"]
        )
    return st.session_state["sb"]


def log_out():
    try:
        st.session_state["sb"].auth.sign_out()
    except Exception:
        pass
    st.session_state.clear()


def require_login():
    """Show the login form until the person is signed in. Returns their connection."""
    sb = get_client()

    if st.session_state.get("user_email"):
        with st.sidebar:
            st.caption("Signed in as " + st.session_state["user_email"])
            st.button("Log out", on_click=log_out)
        return sb

    st.title("📚 StudyBuddy")
    with st.form("login"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")

    if submitted:
        try:
            result = sb.auth.sign_in_with_password({"email": email, "password": password})
            st.session_state["user_email"] = result.user.email
            st.rerun()
        except Exception as error:
            print("Login failed:", error)
            st.error("Wrong email or password.")

    st.stop()  # nothing below this line runs until they are signed in
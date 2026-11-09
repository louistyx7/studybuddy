#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Nov  9 15:36:57 2026

@author: louis
"""

import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()  # on your Mac: reads .env

# On Streamlit Community Cloud: copy the saved "secrets" into environment variables
for name in ["ANTHROPIC_API_KEY", "SUPABASE_URL", "SUPABASE_KEY"]:
    if not os.environ.get(name):
        try:
            os.environ[name] = st.secrets[name]
        except Exception:
            pass  # no secrets file on your Mac, which is fine
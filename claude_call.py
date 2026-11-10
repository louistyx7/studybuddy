#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Nov 10 10:11:24 2026

@author: louis
"""

"""claude_call.py - one safe way to ask Claude to fill in a tool 'form'."""


def call_with_tool(client, *, model, system, user_text, tool, max_tokens, effort=None):
    """Send one request and return the finished response.
    It streams, because long answers can take a couple of minutes."""
    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "tools": [tool],
        "messages": [{"role": "user", "content": user_text}],
    }
    if effort:  # "low" = think less (cheaper and faster). Thinking tokens count towards max_tokens.
        kwargs["extra_body"] = {"output_config": {"effort": effort}}
    with client.messages.stream(**kwargs) as stream:
        return stream.get_final_message()
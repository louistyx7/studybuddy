#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Nov  9 12:56:45 2026

@author: louis
"""

from dotenv import load_dotenv
import anthropic

# Read the secret key from the .env file
load_dotenv()

# Create the connection to Claude (it finds ANTHROPIC_API_KEY by itself)
client = anthropic.Anthropic()

# Send one short message to the cheap model
response = client.messages.create(
    model="claude-haiku-5-5",
    max_tokens=300,
    messages=[
        {"role": "user", "content": "Say hello in one short sentence and name one tip for studying."}
    ],
)

# Print only the text parts of the reply
for block in response.content:
    if block.type == "text":
        print(block.text)

# Show how much the request used (this is what you pay for)
print("Tokens in:", response.usage.input_tokens)
print("Tokens out:", response.usage.output_tokens)
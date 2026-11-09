from dotenv import load_dotenv
import anthropic

from pdf_reader import extract_pdf_text  # the function from Step 3.1

# Read the secret key from .env and open the connection to Claude
load_dotenv()
client = anthropic.Anthropic()

# The cheap model is our default
MODEL_CHEAP = "claude-haiku-5-5"

# Most characters of lecture text we will send (keeps each request cheap)
MAX_CHARS = 120_000

# Standing instructions for how Claude should write the notes
NOTES_INSTRUCTIONS = """You are a study-notes assistant for a university student.
Turn the lecture text you are given into clear study notes by calling the save_notes tool exactly once.

Rules:
- Use ONLY information found in the lecture text. Do not invent facts or numbers.
- Keep the notes concise: about 8-12 key concepts and 8-12 important terms.
- The text came from slides, so pictures and layout are not visible to you.
  Only use missing_content_note when specific numbers, labels or figures are clearly
  missing or unreadable. Do not comment on layout, reading order or design.
  Otherwise leave it empty.
- diagram: only if the lecture clearly contains a process, a sequence of stages,
  or a hierarchy, write a small Graphviz DOT diagram (at most 10 nodes, short
  labels, every label in double quotes). Otherwise leave it as an empty string.
  Example: digraph { rankdir=LR; node [shape=box]; "Stage 1" -> "Stage 2"; }"""

# The "form" Claude fills in. Each property is one labelled box.
# "strict": True forces Claude to fill every box correctly.
NOTES_TOOL = {
    "name": "save_notes",
    "description": "Save the finished study notes.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "overview": {"type": "string", "description": "2-3 sentences"},
            "key_concepts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "explanation": {"type": "string"},
                    },
                    "required": ["title", "explanation"],
                    "additionalProperties": False,
                },
            },
            "important_terms": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "term": {"type": "string"},
                        "definition": {"type": "string"},
                    },
                    "required": ["term", "definition"],
                    "additionalProperties": False,
                },
            },
            "summary": {"type": "string", "description": "3-5 sentences"},
            "diagram": {"type": "string", "description": "Graphviz DOT code, or an empty string"},
            "missing_content_note": {"type": "string", "description": "Empty if nothing seems missing"},
        },
        "required": [
            "overview", "key_concepts", "important_terms",
            "summary", "diagram", "missing_content_note",
        ],
        "additionalProperties": False,
    },
}

REQUIRED_KEYS = [
    "overview", "key_concepts", "important_terms",
    "summary", "diagram", "missing_content_note",
]


def notes_look_complete(notes):
    """Safety net: check that every box exists and the lists really are lists."""
    return (
        all(key in notes for key in REQUIRED_KEYS)
        and isinstance(notes["key_concepts"], list)
        and isinstance(notes["important_terms"], list)
        and len(notes["key_concepts"]) > 0
    )


def generate_notes(lecture_text, model=MODEL_CHEAP):
    """Send lecture text to Claude. Returns (notes_dict, tokens_in, tokens_out)."""
    if len(lecture_text) > MAX_CHARS:
        raise ValueError("This file has too much text. Please upload a shorter one.")

    total_in = 0
    total_out = 0

    # Try up to 2 times, in case the form comes back incomplete
    for attempt in range(2):
        response = client.messages.create(
            model=model,
            max_tokens=8000,
            system=NOTES_INSTRUCTIONS,
            tools=[NOTES_TOOL],
            messages=[
                {"role": "user", "content": "Here is the lecture text:\n\n" + lecture_text}
            ],
        )
        total_in += response.usage.input_tokens
        total_out += response.usage.output_tokens

        # If Claude ran out of room, the form would be half-filled, so stop here
        if response.stop_reason == "max_tokens":
            raise ValueError("The notes were cut off because they hit the length limit. Try a shorter file.")

        # Look for a properly filled-in form
        for block in response.content:
            if block.type == "tool_use" and block.name == "save_notes":
                if notes_look_complete(block.input):
                    return block.input, total_in, total_out

        print(f"Attempt {attempt + 1}: the notes came back incomplete, trying again...")

    raise ValueError("Claude did not return complete notes. Please try again.")


# Quick self-test: only runs when you run this file directly
if __name__ == "__main__":
    text, pages = extract_pdf_text("sample.pdf")
    notes, tokens_in, tokens_out = generate_notes(text)

    print("OVERVIEW:", notes["overview"])
    print()
    print("KEY CONCEPTS:", len(notes["key_concepts"]))
    for item in notes["key_concepts"]:
        print("  -", item["title"])
    print()
    print("TERMS:", len(notes["important_terms"]))
    print()
    print("DIAGRAM CODE:")
    print(notes["diagram"] or "(none)")
    print()
    print("MISSING CONTENT NOTE:", notes["missing_content_note"] or "(none)")
    print()
    print("Tokens in:", tokens_in)
    print("Tokens out:", tokens_out)
    cost = tokens_in * 0.10 / 1_000_000 + tokens_out * 0.50 / 1_000_000
    print(f"Estimated cost: ${cost:.5f}")
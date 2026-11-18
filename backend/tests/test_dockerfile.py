"""The image must carry everything the app reads from the repo at runtime."""

import re
from pathlib import Path

from phoebe.chat.prompt import ANSWER_PROMPT_PATH

REPO = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO / "backend" / "Dockerfile"


def runtime_copies() -> list[tuple[str, str]]:
    """(source, destination) of every COPY in the runtime-base stage."""
    text = DOCKERFILE.read_text()
    stage = text.split("AS runtime-base", 1)[1].split("\nFROM ", 1)[0]
    return [
        (m.group(1), m.group(2))
        for m in re.finditer(r"^COPY (?:--\S+ )*(\S+) (\S+)$", stage, re.MULTILINE)
    ]


def test_image_ships_the_prompt() -> None:
    # The converse backend reads backend/prompts/answer.txt at startup; the app
    # runs from /app/backend/src (PYTHONPATH), so the prompt must be at
    # /app/backend/prompts.
    rel = ANSWER_PROMPT_PATH.relative_to(REPO / "backend").parent  # prompts
    assert (f"backend/{rel}", f"/app/backend/{rel}") in runtime_copies()

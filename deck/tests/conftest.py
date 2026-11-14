"""Import app before anything reads configuration.

Deck reads its environment at module level, the same as api and reports, so
the environment has to be set before the import rather than inside a fixture.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("API_URL", "http://core.test:8080")
os.environ.setdefault("DECK_PORT", "5555")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

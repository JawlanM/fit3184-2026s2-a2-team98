"""Species-name cleanup from labels.json (D-04).

Unknown species pass through unchanged: a swapped-in model may report a
species this list doesn't have yet, and its tags must still be stored.
"""
import json
from pathlib import Path

_DATA = json.loads((Path(__file__).parent / "labels.json").read_text(encoding="utf-8"))

SPECIES = tuple(_DATA["species"])

_ALIASES = {syn: name
            for name, v in _DATA["species"].items()
            for syn in [name, *v.get("synonyms", [])]}

_REKOGNITION = {r.lower(): name
                for name, v in _DATA["species"].items()
                for r in v.get("rekognition", [])}


def normalise(raw: str) -> str:
    """'  Cane   Toad ' -> 'cane toad'; 'toads' -> 'cane toad'; 'quoll' -> 'quoll'."""
    s = " ".join(raw.strip().lower().split())
    return _ALIASES.get(s, s)


def from_rekognition(label: str) -> str | None:
    """Rekognition's 'Fox' -> 'fox'. None for labels we don't track (B's fallback)."""
    return _REKOGNITION.get(label.strip().lower())

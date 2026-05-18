"""Alias tool: same as ``fauxplexica_search`` but named for answer-style usage."""

from __future__ import annotations

from pathlib import Path
import sys

_PLUGIN_PARENT = Path(__file__).resolve().parents[2]
if str(_PLUGIN_PARENT) not in sys.path:
    sys.path.append(str(_PLUGIN_PARENT))

from a0_fauxplexica.tools.fauxplexica_search import FauxplexicaSearch


class FauxplexicaAnswer(FauxplexicaSearch):
    """Compose-final-answer tool — runs the Fauxplexica pipeline."""

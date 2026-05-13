"""Alias tool: same as ``fauxplexica_search`` but named for answer-style usage."""

from __future__ import annotations

from plugins.a0_fauxplexica.tools.fauxplexica_search import FauxplexicaSearch


class FauxplexicaAnswer(FauxplexicaSearch):
    """Compose-final-answer tool — runs the Fauxplexica pipeline."""

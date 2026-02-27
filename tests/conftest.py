"""Shared test fixtures — auto-reset module-level state between tests."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_salvage_state():
    """Reset salvage module state before each test to prevent leakage."""
    import server.game_loop_salvage as glsalv
    glsalv.reset()
    yield
    glsalv.reset()

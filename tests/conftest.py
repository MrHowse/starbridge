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


@pytest.fixture(autouse=True)
def _reset_rationing_state():
    """Reset rationing module state before each test to prevent leakage."""
    import server.game_loop_rationing as glrat
    glrat.reset()
    yield
    glrat.reset()


@pytest.fixture(autouse=True)
def _reset_operations_state():
    """Reset operations module state before each test to prevent leakage."""
    import server.game_loop_operations as glops
    glops.reset()
    yield
    glops.reset()


@pytest.fixture(autouse=True)
def _reset_atmosphere_state():
    """Reset atmosphere module state before each test to prevent leakage."""
    import server.game_loop_atmosphere as glatm
    glatm.reset()
    yield
    glatm.reset()


@pytest.fixture(autouse=True)
def _reset_hazard_control_state():
    """Reset hazard control module state before each test to prevent leakage."""
    import server.game_loop_hazard_control as glhc
    glhc.reset()
    yield
    glhc.reset()


@pytest.fixture(autouse=True)
def _reset_captain_orders_state():
    """Reset captain orders module state before each test to prevent leakage."""
    import server.game_loop_captain_orders as glcord
    glcord.reset()
    yield
    glcord.reset()

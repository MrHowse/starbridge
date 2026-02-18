"""
Mission Engine — Runtime mission execution.

Evaluates mission triggers each tick, fires events when conditions are met,
tracks objective completion, and manages mission state transitions
(briefing → active → complete/failed → debrief).
Implemented in Phase 6.
"""
from __future__ import annotations

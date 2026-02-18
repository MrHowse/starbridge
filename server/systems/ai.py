"""
Enemy AI — Behaviour state machine.

Simple state machine for enemy ships: idle → chase → attack → flee.
State transitions based on distance to player, health thresholds, and
weapon range. Each enemy type has different parameters.
Implemented in Phase 4.
"""
from __future__ import annotations

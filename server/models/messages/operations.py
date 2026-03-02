"""Operations station message payload schemas.

Schemas are added as Operations features are implemented (A.2–A.5).
"""
from __future__ import annotations

from pydantic import BaseModel


class OperationsPingPayload(BaseModel):
    """Minimal keep-alive / heartbeat — ensures structural tests pass.

    Expanded with real schemas in A.2–A.5.
    """
    pass

"""
Rationing Game Loop — v0.07 Phase 6.6.

Module-level state machine for per-resource consumption limits with
effectiveness penalties, a cross-station allocation request queue, and
resource burn-rate forecasting.

Public API:
  reset(), serialise(), deserialise(), pop_pending_events()
  set_ration_level(), get_ration_level(), get_ration_levels()
  get_consumption_multiplier(), get_effectiveness_multiplier()
  captain_override()
  submit_request(), approve_request(), deny_request()
  get_pending_requests(), auto_process_requests()
  record_consumption(), update_forecasts(), get_forecasts()
  tick()
"""
from __future__ import annotations

from server.models.rationing import (
    RATION_LEVELS,
    RATION_CONSUMPTION_MULT,
    RATION_EFFECTIVENESS_MULT,
    FORECAST_WINDOW,
    FORECAST_UPDATE_INTERVAL,
    AUTO_APPROVE_THRESHOLD,
    RESOURCE_TYPES,
    FORECAST_COLOUR_RED,
    FORECAST_COLOUR_AMBER,
    AllocationRequest,
    ResourceForecast,
)
from server.models.ship import Ship


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_ration_levels: dict[str, str] = {}           # resource_type → level
_allocation_requests: list[AllocationRequest] = []
_request_counter: int = 0
_pending_events: list[dict] = []
_consumption_history: dict[str, list[tuple[float, float]]] = {}  # type → [(tick_time, amount)]
_last_forecast_time: float = 0.0
_forecasts: dict[str, ResourceForecast] = {}
_captain_overrides: set[str] = set()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def reset() -> None:
    """Clear all rationing state for a new game."""
    global _request_counter, _last_forecast_time
    _ration_levels.clear()
    _allocation_requests.clear()
    _request_counter = 0
    _pending_events.clear()
    _consumption_history.clear()
    _last_forecast_time = 0.0
    _forecasts.clear()
    _captain_overrides.clear()


def serialise() -> dict:
    """Serialise rationing state for save system."""
    return {
        "ration_levels": dict(_ration_levels),
        "allocation_requests": [r.to_dict() for r in _allocation_requests],
        "request_counter": _request_counter,
        "captain_overrides": list(_captain_overrides),
        "last_forecast_time": _last_forecast_time,
    }


def deserialise(data: dict) -> None:
    """Restore rationing state from save data."""
    global _request_counter, _last_forecast_time
    _ration_levels.clear()
    _allocation_requests.clear()
    _pending_events.clear()
    _consumption_history.clear()
    _forecasts.clear()
    _captain_overrides.clear()

    _ration_levels.update(data.get("ration_levels", {}))
    for rd in data.get("allocation_requests", []):
        _allocation_requests.append(AllocationRequest.from_dict(rd))
    _request_counter = data.get("request_counter", 0)
    _captain_overrides.update(data.get("captain_overrides", []))
    _last_forecast_time = data.get("last_forecast_time", 0.0)


def pop_pending_events() -> list[dict]:
    """Return and clear pending events for broadcast."""
    events = list(_pending_events)
    _pending_events.clear()
    return events


# ---------------------------------------------------------------------------
# Rationing levels
# ---------------------------------------------------------------------------


def set_ration_level(resource_type: str, level: str) -> dict:
    """Set the ration level for a resource type.

    Validates that resource_type and level are known.
    Emits 'ration_level_changed' event.
    """
    if resource_type not in RESOURCE_TYPES:
        return {"ok": False, "error": "invalid_resource_type"}
    if level not in RATION_LEVELS:
        return {"ok": False, "error": "invalid_level"}

    old_level = _ration_levels.get(resource_type, "unrestricted")
    if old_level == level:
        return {"ok": False, "error": "already_at_level"}

    _ration_levels[resource_type] = level
    # Remove any captain override when explicitly setting a level.
    _captain_overrides.discard(resource_type)

    _pending_events.append({
        "type": "ration_level_changed",
        "resource_type": resource_type,
        "old_level": old_level,
        "new_level": level,
    })
    return {"ok": True}


def get_ration_level(resource_type: str) -> str:
    """Return the current ration level for a resource type."""
    return _ration_levels.get(resource_type, "unrestricted")


def get_ration_levels() -> dict[str, str]:
    """Return all ration levels (only those explicitly set)."""
    return dict(_ration_levels)


def get_consumption_multiplier(resource_type: str) -> float:
    """Return the consumption multiplier for a resource type.

    Returns 1.0 if captain override is active or level is unrestricted.
    """
    if resource_type in _captain_overrides:
        return 1.0
    level = _ration_levels.get(resource_type, "unrestricted")
    return RATION_CONSUMPTION_MULT[level]


def get_effectiveness_multiplier(resource_type: str) -> float:
    """Return the effectiveness multiplier for a resource type.

    Returns 1.0 if captain override is active or level is unrestricted.
    """
    if resource_type in _captain_overrides:
        return 1.0
    level = _ration_levels.get(resource_type, "unrestricted")
    return RATION_EFFECTIVENESS_MULT[level]


def captain_override(resource_type: str) -> dict:
    """Captain override: reset resource to unrestricted and mark overridden.

    Emits 'captain_override' event.
    """
    if resource_type not in RESOURCE_TYPES:
        return {"ok": False, "error": "invalid_resource_type"}

    old_level = _ration_levels.get(resource_type, "unrestricted")
    _ration_levels[resource_type] = "unrestricted"
    _captain_overrides.add(resource_type)

    _pending_events.append({
        "type": "captain_override",
        "resource_type": resource_type,
        "old_level": old_level,
    })
    return {"ok": True}


# ---------------------------------------------------------------------------
# Allocation requests
# ---------------------------------------------------------------------------


def submit_request(
    source_station: str,
    resource_type: str,
    quantity: float,
    reason: str,
    tick: int,
    ship: Ship | None = None,
) -> dict:
    """Submit a cross-station allocation request.

    If *ship* is provided, calculates impact_preview (fraction remaining after
    approval).
    """
    global _request_counter
    if resource_type not in RESOURCE_TYPES:
        return {"ok": False, "error": "invalid_resource_type"}
    if quantity <= 0:
        return {"ok": False, "error": "invalid_quantity"}

    _request_counter += 1
    req_id = f"alloc_{_request_counter}"

    impact = 0.0
    if ship is not None and hasattr(ship, "resources"):
        current = ship.resources.get(resource_type)
        capacity = ship.resources.get_max(resource_type)
        if capacity > 0:
            impact = max(0.0, (current - quantity)) / capacity

    req = AllocationRequest(
        id=req_id,
        source_station=source_station,
        resource_type=resource_type,
        quantity=quantity,
        reason=reason,
        created_tick=tick,
        impact_preview=round(impact, 4),
    )
    _allocation_requests.append(req)

    _pending_events.append({
        "type": "request_submitted",
        "request": req.to_dict(),
    })
    return {"ok": True, "request_id": req_id}


def approve_request(request_id: str, ship: Ship) -> dict:
    """Approve a pending allocation request and transfer resources."""
    req = _find_request(request_id)
    if req is None:
        return {"ok": False, "error": "request_not_found"}
    if req.status != "pending":
        return {"ok": False, "error": "request_not_pending"}

    # Check sufficient stock.
    available = ship.resources.get(req.resource_type)
    if available < req.quantity:
        return {"ok": False, "error": "insufficient_stock"}

    # Transfer resources.
    ship.resources.consume(req.resource_type, req.quantity)
    req.status = "approved"

    _pending_events.append({
        "type": "request_approved",
        "request_id": req.id,
        "resource_type": req.resource_type,
        "quantity": req.quantity,
        "source_station": req.source_station,
    })
    return {"ok": True}


def deny_request(request_id: str, reason: str = "") -> dict:
    """Deny a pending allocation request."""
    req = _find_request(request_id)
    if req is None:
        return {"ok": False, "error": "request_not_found"}
    if req.status != "pending":
        return {"ok": False, "error": "request_not_pending"}

    req.status = "denied"
    req.denial_reason = reason

    _pending_events.append({
        "type": "request_denied",
        "request_id": req.id,
        "resource_type": req.resource_type,
        "reason": reason,
    })
    return {"ok": True}


def get_pending_requests() -> list[AllocationRequest]:
    """Return all pending allocation requests."""
    return [r for r in _allocation_requests if r.status == "pending"]


def auto_process_requests(ship: Ship, is_crewed: bool) -> None:
    """Auto-approve requests when uncrewed and stock > 50%.

    When no captain is present, requests above the auto-approve threshold
    are automatically approved; those below are left pending.
    """
    if is_crewed:
        return

    for req in _allocation_requests:
        if req.status != "pending":
            continue
        fraction = ship.resources.fraction(req.resource_type)
        if fraction > AUTO_APPROVE_THRESHOLD:
            approve_request(req.id, ship)


# ---------------------------------------------------------------------------
# Forecasting
# ---------------------------------------------------------------------------


def record_consumption(resource_type: str, amount: float, tick_time: float) -> None:
    """Record a resource consumption event for burn-rate tracking."""
    if amount <= 0:
        return
    history = _consumption_history.setdefault(resource_type, [])
    history.append((tick_time, amount))


def update_forecasts(ship: Ship, route_distance: float, tick_time: float) -> None:
    """Recalculate burn-rate forecasts for all resource types.

    Only runs every FORECAST_UPDATE_INTERVAL seconds.
    *route_distance*: remaining distance to destination (-1 if no route).
    """
    global _last_forecast_time
    if tick_time - _last_forecast_time < FORECAST_UPDATE_INTERVAL:
        return
    _last_forecast_time = tick_time

    cutoff = tick_time - FORECAST_WINDOW

    for rtype in RESOURCE_TYPES:
        # Prune old history.
        history = _consumption_history.get(rtype, [])
        history[:] = [(t, a) for t, a in history if t >= cutoff]

        # Calculate burn rate (units/sec).
        total_consumed = sum(a for _, a in history)
        window = min(FORECAST_WINDOW, max(tick_time, 0.001))
        burn_rate = total_consumed / window if window > 0 else 0.0

        current = ship.resources.get(rtype)
        capacity = ship.resources.get_max(rtype)

        # Seconds to depletion.
        if burn_rate > 0:
            seconds_to_depletion = current / burn_rate
        else:
            seconds_to_depletion = -1.0

        # Colour coding.
        fraction = current / capacity if capacity > 0 else 1.0
        if fraction <= FORECAST_COLOUR_RED:
            colour = "flashing_red" if burn_rate > 0 else "red"
        elif fraction <= FORECAST_COLOUR_AMBER:
            colour = "amber"
        else:
            colour = "green"

        # Projected at destination.
        projected = -1.0
        if route_distance > 0 and burn_rate > 0:
            # Estimate travel time from current ship velocity.
            ship_speed = getattr(ship, "velocity", 0.0)
            if ship_speed > 0:
                travel_time = route_distance / ship_speed
                projected = max(0.0, current - burn_rate * travel_time)
            else:
                projected = -1.0

        _forecasts[rtype] = ResourceForecast(
            resource_type=rtype,
            current=current,
            capacity=capacity,
            burn_rate=burn_rate,
            seconds_to_depletion=seconds_to_depletion,
            colour=colour,
            projected_at_destination=projected,
        )


def get_forecasts() -> dict[str, ResourceForecast]:
    """Return all current resource forecasts."""
    return dict(_forecasts)


# ---------------------------------------------------------------------------
# Tick
# ---------------------------------------------------------------------------


def tick(
    ship: Ship,
    dt: float,
    route_distance: float,
    is_crewed: bool,
    tick_time: float,
) -> None:
    """Advance rationing state by *dt* seconds.

    - Auto-process allocation requests when uncrewed
    - Update burn-rate forecasts
    """
    auto_process_requests(ship, is_crewed)
    update_forecasts(ship, route_distance, tick_time)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_request(request_id: str) -> AllocationRequest | None:
    for req in _allocation_requests:
        if req.id == request_id:
            return req
    return None

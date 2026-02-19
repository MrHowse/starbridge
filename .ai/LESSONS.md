# Lessons Learned

> **APPEND-ONLY** — Add new lessons at the bottom. Never modify or remove existing entries.
> Record anything that went wrong, caused confusion, or wasted time so future sessions avoid repeating it.

---

## Template

Copy this template when adding a new entry:

```
## [Date] — [Brief title]

**Issue**: What went wrong
**Cause**: Why it happened
**Fix**: How it was resolved
**Prevention**: How to avoid this in future sessions
```

---

## 2026-02-18 — Pyright false positive on field_validator import

**Issue**: Pyright reported `field_validator` as "not accessed" even though it was used as a decorator (`@field_validator("player_name")`).
**Cause**: Pyright's analysis of decorator-factory usage can miss the reference in some configurations, especially with `from __future__ import annotations` in scope.
**Fix**: The code was functionally correct and all tests passed. Treated as a known false positive and proceeded.
**Prevention**: If this recurs, try suppressing with `# type: ignore[reportUnusedImport]` on the import line, or restructure to use `model_validator` instead if it avoids the issue.

---

## 2026-02-18 — Late-join clients miss one-shot broadcasts

**Issue**: Station pages (helm, captain, etc.) load fresh after the lobby redirect, opening a new WebSocket. By the time they connect, `game.started` has already been broadcast and will never be sent again — the station stays on its standby screen indefinitely.
**Cause**: One-shot broadcast pattern: `game.started` fires once when the host launches. Any client connecting afterward never receives it.
**Fix**: Store the `game.started` payload in `lobby._game_payload`. In `on_connect()`, if the game is already running, send `game.started` directly to the new connection and return early (skipping `lobby.state`).
**Prevention**: Any one-shot server→client message that must reach future joiners needs a stored copy. Pattern: store payload at broadcast time, re-send to every new connect when game is active.

---

## 2026-02-18 — Wrong station page due to role confusion in the lobby redirect

**Issue**: User claimed the Captain role and was redirected to `/client/captain/` — a placeholder page with no content. They expected to see the Helm station. Debugging consumed multiple rounds.
**Cause**: `lobby.js` calls `redirectToStation(myRole)` on `game.started`. `myRole` is determined by matching the callsign input against the server's role list. If the user claims Captain, they go to the Captain page, not Helm.
**Fix**: No code fix needed in the redirect logic. Fixed by:
  1. Adding "← RETURN TO LOBBY" link to all placeholder station pages
  2. Changing standby text to "This station is not yet operational" for unimplemented stations
**Prevention**: Make placeholder pages clearly distinct from working stations. All placeholder standby screens must have a lobby return link. Test the full role-claim → redirect flow explicitly, not just the helm-specific path.

---

## 2026-02-18 — TestClient WebSocket message counting requires careful tracing

**Issue**: Integration tests with multiple WebSocket clients need careful accounting of which broadcasts arrive on which connection. Easy to off-by-one the `receive_json()` calls.
**Cause**: `on_connect` sends a welcome to the new client then broadcasts `lobby.state` to ALL connected clients. In a two-client test, the first client gets an extra `lobby.state` when the second client connects.
**Fix**: Trace the message sequence per-client before writing receive calls. Only consume what a given client actually receives.
**Prevention**: Add a comment per `receive_json()` call explaining which server event produced it. Leave unread messages on older clients if you're only testing the newer client's responses.

---

## 2026-02-18 — State files must be updated at the end of every session, not deferred

**Issue**: Phase 4 was built in full (244 tests passing) while `.ai/STATE.md` still showed Phase 3 data, `.ai/PHASE_CURRENT.md` still described Phase 4 as a future plan with unchecked task boxes, and `.ai/DECISIONS.md` was missing all Phase 4 architectural decisions.
**Cause**: Implementation sessions focused on code and tests without circling back to update the project state documents. The state files were treated as documentation to be updated "eventually" rather than as live context required by the next session.
**Fix**: Updated all state files at the start of the following session before any further work proceeded.
**Prevention**: State files must be updated at the end of every session, not deferred. If a different model or a new session had picked this up, it would have had stale context and potentially duplicated or conflicted with existing work. The rule is: no session ends without STATE.md, PHASE_CURRENT.md, and DECISIONS.md reflecting the actual state of the codebase.

---

## 2026-02-19 — Scope document contained incorrect AP regen math

**Issue**: The v0.02 scope document (docs/SCOPE_v002.md) stated that marine action point pools fill "in 25 seconds." The correct calculation gives 5 seconds.
**Cause**: The scope doc's maths assumed 1 AP per 25 ticks (1 AP per 2.5 seconds). The design intent was 1 AP per 5 ticks (1 AP per 0.5 seconds). At 10 ticks/second: 10 AP ÷ (1 AP / 5 ticks) × 0.1 s/tick = 5 seconds to fill from empty.
**Fix**: Implemented correctly in `server/models/security.py` as `AP_REGEN_PER_TICK = 0.2` (= 1/5). Recorded in DECISIONS.md. Scope doc left as-is (it is a historical planning document, not a live spec).
**Prevention**: When transcribing tuning parameters from a scope/design document, always verify the math against desired feel before implementing. At 10 ticks/second, "fill in N seconds" = AP_MAX / (N × 10) AP per tick. State the desired UX outcome ("move every 1.5 seconds from empty") alongside the constant, not just the constant — the outcome is the invariant.

---

## 2026-02-18 — Budget gauge alarm at comfortable equilibrium

**Issue**: The Engineering power budget gauge immediately turned red on game start because all 6 systems start at 100% each = 600/600 total = exactly at the budget cap. The threshold condition `totalPower >= POWER_BUDGET` was true from the very first server tick.
**Cause**: When designing threshold-based colour alerts, the default/equilibrium state was not checked against the threshold values. The comfortable starting state (600/600) happened to sit exactly on the "critical" threshold.
**Fix**: Removed colour thresholds from the budget bar entirely. It always renders in primary green. Per-system overclock indicators (amber slider thumb via `.sys-row--overclocked`, repair focus glow on schematic node) handle the per-system warning role.
**Prevention**: Before writing any alert threshold, verify what the system's comfortable/default state value is and ensure it falls well below all thresholds. If the comfortable state is at or above a threshold, the threshold is wrong — not the default state. The fix is typically to remove or redesign the indicator, because it is answering the wrong question.

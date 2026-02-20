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

## 2026-02-19 — File manifest drift: synthetic mission listed as a JSON file

**Issue**: During v0.02 gate verification, `missions/sandbox.json` appeared to be missing — it was listed in STATE.md's file manifest but absent from the filesystem.
**Cause**: The file manifest in STATE.md was written during Phase 6 when sandbox was originally planned as a JSON file, then the implementation switched to a synthetic dict in `loader.py`. The manifest was never corrected.
**Fix**: Removed `missions/sandbox.json` from the manifest and added a clear note: "Sandbox is synthetic — no JSON file. Handled in loader.py."
**Prevention**: When a design decision changes the form of an artefact (file vs synthetic, module vs config), update the file manifest immediately, not at gate time. File manifests are load-bearing context for future sessions.

---

## 2026-02-20 — Mission JSON files missing required top-level "id" field

**Issue**: `boarding_action.json` and `first_contact_protocol.json` were missing the `"id"` field at the JSON top level. `test_gate_v003.py::test_loads[boarding_action]` failed with `KeyError: 'id'` during gate verification — the first time these missions had been tested with the gate's identity assertion.
**Cause**: Both files were authored during v0.02c development when the mission file template was copied without double-checking all required top-level keys. The `id` field is not needed by `load_mission()` itself (it returns the raw dict) so the missing field went unnoticed during normal mission engine tests, which access individual objective fields rather than the top-level identity.
**Fix**: Prepended `"id": "boarding_action"` / `"id": "first_contact_protocol"` to each JSON file.
**Prevention**: Gate tests should include an `assert mission["id"] == mid` assertion — as `test_gate_v003.py` now does. When authoring any new mission JSON, immediately verify the file round-trips through `load_mission(id)["id"] == id`. Add a lint/validate step to the sub-release checklist that verifies every JSON mission file has the required top-level keys (`id`, `objectives`, `victory_condition`).

---

## 2026-02-20 — Scope drift: point_defence system declared but never implemented

**Issue**: The v0.02 scope document listed `point_defence` as a battleship-exclusive ship system. The v0.03o gate verification confirmed it is absent from `server/models/ship.py`. The default ship has 8 systems; `point_defence` was never implemented.
**Cause**: The scope document was written speculatively for a multi-phase roadmap. The battleship class was added in v0.03o as a data-model-only entry (hull/ammo/crew values). The gameplay mechanic (point defence turrets against torpedoes) was never scoped into any sprint.
**Fix**: Not fixed — documented as a known gap at v0.03 close. It is a v0.04 candidate.
**Prevention**: When a scope document lists a new ship system, create a corresponding failing test or placeholder in `ship.py` immediately. Scope-declared systems that have no code anchor will drift and may not be caught until a gate test explicitly checks for them. Rule: if the scope says "battleship has X", `ship.py` gets a stub entry for X in the same session.

---

## 2026-02-20 — Stale phase string in health endpoint

**Issue**: Server health endpoint (`GET /`) returns `"phase": "4 — Weapons Station + Combat"` even at v0.03 close. The string predates v0.03 by 6+ months of development.
**Cause**: `server/main.py` has a hardcoded phase string that was set in Phase 4 and never updated. It is not driven by any state file or configuration.
**Fix**: Not fixed at v0.03 close — not blocking. Reported as a known gap.
**Prevention**: The health endpoint's `phase` field should either (a) read from a file (e.g. `.ai/PHASE_CURRENT.md` first line), or (b) be removed and replaced with a `version` field that is driven by a single source of truth. Hardcoded descriptive strings in server code will always become stale. Update this at the start of v0.04.

---

## 2026-02-18 — Budget gauge alarm at comfortable equilibrium

**Issue**: The Engineering power budget gauge immediately turned red on game start because all 6 systems start at 100% each = 600/600 total = exactly at the budget cap. The threshold condition `totalPower >= POWER_BUDGET` was true from the very first server tick.
**Cause**: When designing threshold-based colour alerts, the default/equilibrium state was not checked against the threshold values. The comfortable starting state (600/600) happened to sit exactly on the "critical" threshold.
**Fix**: Removed colour thresholds from the budget bar entirely. It always renders in primary green. Per-system overclock indicators (amber slider thumb via `.sys-row--overclocked`, repair focus glow on schematic node) handle the per-system warning role.
**Prevention**: Before writing any alert threshold, verify what the system's comfortable/default state value is and ensure it falls well below all thresholds. If the comfortable state is at or above a threshold, the threshold is wrong — not the default state. The fix is typically to remove or redesign the indicator, because it is answering the wrong question.

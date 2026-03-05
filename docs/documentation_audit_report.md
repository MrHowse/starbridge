# Documentation Audit Report

**Date:** 2026-03-05
**Scope:** All player-facing documentation — manual, help screens, FAQ, about, lobby, README

---

## File Inventory

| Path | Type | Status |
|------|------|--------|
| `client/site/manual/index.html` | manual | Updated |
| `client/site/manual/shortcuts.html` | shortcut reference | **NEW** |
| `client/site/faq/index.html` | faq | Updated |
| `client/site/about/index.html` | about | Updated |
| `client/site/index.html` | landing page | Updated |
| `client/lobby/lobby.js` (ROLE_DESCRIPTIONS) | lobby | Current |
| `client/shared/help_overlay.js` | help infrastructure | Current |
| `client/captain/captain.js` (registerHelp) | help overlay | Current |
| `client/helm/helm.js` (registerHelp) | help overlay | Current |
| `client/weapons/weapons.js` (registerHelp) | help overlay | Current |
| `client/engineering/engineering.js` (registerHelp) | help overlay | Current |
| `client/science/science.js` (registerHelp) | help overlay | Current |
| `client/medical/medical.js` (registerHelp) | help overlay | Current |
| `client/security/security.js` (registerHelp) | help overlay | Current |
| `client/comms/comms.js` (registerHelp) | help overlay | Current |
| `client/operations/operations.js` (registerHelp) | help overlay | Current |
| `client/flight_ops/flight_ops.js` (registerHelp) | help overlay | **NEW** |
| `client/ew/ew.js` (registerHelp) | help overlay | **NEW** |
| `client/hazard_control/hazard_control.js` (registerHelp) | help overlay | **NEW** |
| `client/quartermaster/quartermaster.js` (registerHelp) | help overlay | **NEW** |
| `README.md` | project readme | Updated |
| `server/main.py` (/health, /api/status) | version endpoint | Updated |

---

## Keyboard Shortcut Registry

Extracted from code — see `client/site/manual/shortcuts.html` for the complete printable reference.

### Summary

| Station | Shortcuts | Source File |
|---------|-----------|-------------|
| Global | 4 (F1, Esc, C, [/]) | help_overlay.js, crew_roster.js, range_control.js |
| Crew Roster | 5 (F, S, arrows, Enter, Esc) | crew_roster.js |
| Captain | 4 (1-6, H, L, Enter) | captain.js |
| Helm | 4 (WASD/arrows) | helm.js |
| Weapons | 7 (arrows, X, Y, C) | weapons.js |
| Engineering | 5 (1-9, D, R, B, Tab) | engineering.js |
| Science | 4 (1-4) | science.js |
| Medical | 8 (arrows, A, D, Q, S, T, 0-5) | medical.js |
| Security | 4 (L, U, Q, Tab) | security.js |
| Flight Ops | 15 (1-9, Tab, L, R, W, P, Enter, D, B, E, T, C, F, Space, Esc) | flight_ops.js |
| Comms | 0 | — |
| EW | 0 | — |
| Operations | 0 | — |
| Hazard Control | 0 | — |
| Quartermaster | 0 | — |

---

## Discrepancies Found

### Shortcuts: 28 missing from manual, 0 phantom, 0 wrong descriptions

Previously the manual listed only Medical (8), Security (4), and Flight Ops (11) shortcuts, plus 4 global. Missing from manual:
- Captain: 1-6, H, L, Enter (4 shortcuts)
- Helm: A/D/W/S + arrows (4 shortcuts)
- Weapons: arrows, X, Y, C (7 shortcuts)
- Engineering: 1-9, D, R, B, Tab (5 shortcuts)
- Science: 1-4 (4 shortcuts)
- Global: C (crew roster), [/] (range) (2 shortcuts)
- Flight Ops: T, F, Space (3 shortcuts missing from existing list)
- Crew roster sub-keys: F, S, arrows, Enter (not documented anywhere)

All now added to manual and shortcut reference card.

### Station Names: 0 stale references

No stale references to "Tactical" or "Damage Control" found — these were fixed in v0.08-polish. Anchor IDs `s-operations` and `s-hazard-control` were already correct.

### Mechanics: 3 outdated descriptions, 1 missing station

1. **Manual Hazard Control section** — described old DC system (room grid, DCT dispatch only). Rewritten to cover v0.08 atmosphere, radiation, structural integrity, fire intensity, overlays.
2. **Manual Engineering section** — incorrectly described shield focus canvas. Shield focus is on Weapons, not Engineering. Replaced with ship interior view description.
3. **FAQ shield focus answer** — said "Engineering station". Fixed to "Weapons station" with keyboard shortcuts.
4. **Quartermaster station** — entirely missing from manual. Added full station guide section.

### Ship Class Stats: 5 wrong hull values

| Class | Manual (old) | Code (actual) | Fixed |
|-------|-------------|---------------|-------|
| Corvette | 80 | 90 | Yes |
| Frigate | 100 | 120 | Yes |
| Cruiser | 140 | 180 | Yes |
| Carrier | 120 | 200 | Yes |
| Battleship | 200 | 300 | Yes |

Fixed in both manual and FAQ.

### Version Strings: 3 stale

| Location | Old | New |
|----------|-----|-----|
| `server/main.py` /health + /api/status | v0.04 | v0.08 |
| `client/site/index.html` footer | v0.06 | v0.08 |
| About page version history | ends at v0.06 | added v0.07 + v0.08 |

### Help Screens: 0 stale, 4 previously missing (now added)

| Station | Status |
|---------|--------|
| Captain | EXISTS — current — F1 |
| Helm | EXISTS — current — F1 |
| Weapons | EXISTS — current — F1 |
| Engineering | EXISTS — current — F1 |
| Science | EXISTS — current — F1 |
| Medical | EXISTS — current — F1 |
| Security | EXISTS — current — F1 |
| Comms | EXISTS — current — F1 |
| Operations | EXISTS — current — F1 |
| Flight Ops | **ADDED** — F1 |
| EW | **ADDED** — F1 |
| Hazard Control | **ADDED** — F1 |
| Quartermaster | **ADDED** — F1 |

### README: Severely outdated

Was v0.01 era (6 roles, 4 missions, 331 tests). Rewritten for v0.08 (13 roles, 7 ship classes, 6,831 tests).

---

## Fixes Applied

1. Manual: Added keyboard shortcut tables for Captain, Helm, Weapons, Engineering, Science (previously listed F1 only)
2. Manual: Converted Medical and Security shortcut lists to table format for consistency
3. Manual: Added T/F/Space shortcuts to Flight Ops table
4. Manual: Rewrote Hazard Control station section for v0.08 (atmosphere, radiation, structural integrity, overlays)
5. Manual: Added Quartermaster station section (resources, rationing, trade, allocation)
6. Manual: Added Quartermaster to table of contents
7. Manual: Fixed Engineering section (removed shield focus canvas, added ship interior view)
8. Manual: Rewrote Keyboard Quick Reference section with all 13 stations
9. Manual: Fixed ship class hull values (Corvette 90, Frigate 120, Cruiser 180, Carrier 200, Battleship 300)
10. FAQ: Fixed ship class hull values
11. FAQ: Fixed shield focus answer (Engineering → Weapons)
12. About: Added v0.07 and v0.08 version history entries
13. Landing page: Updated fallback version v0.06 → v0.08
14. server/main.py: Updated phase v0.04 → v0.08 (health check + api/status)
15. README.md: Complete rewrite for v0.08 (13 roles, ship classes, documentation links)
16. Help overlays: Added registerHelp to Flight Ops, EW, Hazard Control, Quartermaster
17. Tests: Updated phase assertions in test_editor_endpoints.py and test_gate_v004.py
18. Created `client/site/manual/shortcuts.html` — printable keyboard reference card

---

## Shortcut Reference Card

`/client/site/manual/shortcuts.html` — accessible from the manual's Keyboard Reference section. Print-friendly CSS included.

---

## Test Results

**6,831 passed, 0 failed** — zero regressions.

# GUI Round 3 — Session Notes (2026-02-20)

## Implemented (code done, not yet built into exe)

### Round 3a — Original plan (8 items)
All code changes applied to `gui.py` and `db.py`:

1. **Worker visibility** — `db.py`: added `last_heartbeat=now()` to INSERT; `gui.py`: calls `_start_worker_polling()` then `_poll_workers()`
2. **Status label** — replaced `QProgressBar` with `QLabel("Ready")`, all 6 references updated
3. **Filter positioning** — `_reposition_filters()` uses `vp.y() - FILTER_HEIGHT`
4. **Button naming** — "Execute" → "Run Local", `executeBtn` → `runBtn`, dist button gets same objectName
5. **Splitter sizes** — `[300, 900]` → `[900, 300]` (controls 75%, log 25%)
6. _(screenshot review — no additional items)_
7. **Progress text** — `"100% ✓ 5s"` → `"Complete (5s)"` / `"Failed (5s)"`
8. **Arx branding** — near-black buttons, Segoe UI font, dark tab underline, window title "ARX —"

### Round 3b — User testing feedback (3 issues)
After building and testing the exe, user reported 3 issues. Fixes applied to code:

| # | Issue | Root cause | Fix |
|---|-------|-----------|-----|
| 1 | p01 hidden behind filter bar | QTableView `updateGeometries()` resets viewport margins | Added `_in_geom_update` guard; re-apply margins in `updateGeometries()` after `super()` |
| 2 | Worker not in panel after registration | `_start_worker_polling()` returns immediately if already active (from DB connect) | Added explicit `_poll_workers()` call after `_start_worker_polling()` |
| 3 | No per-plan progress; can't tell if running | `run_simulations()` only returns results after ALL plans finish | Added `result_callback` param to `run_simulations()`; parallel path polls `result_queue` instead of join-then-collect; GUI puts results on `progress_queue` for per-plan updates |

### Per-plan progress detail (Issue 3)
- **runner.py**: New `result_callback` parameter on `run_simulations()`. In parallel mode, changed from `join all → collect all` to `poll result_queue with timeout → callback per result → join`. Sequential mode also calls callback after each plan.
- **gui.py**: `_execute()` sets all plans to "Running..." and status to "Running: 0 / N complete". `_run_thread()` passes callback that puts `SimulationResult` on `progress_queue`. `_drain_progress_queue()` handles both `ProgressMessage` and `SimulationResult` via `isinstance`. New `_update_single_plan_result()` updates one plan's row immediately.

## Status
- `ruff check` — clean
- `pytest` — 198 passed
- **Exe NOT yet built** — previous exe was still running, got `PermissionError`
- Next step: close exe, run `pyinstaller HECRAS_Parallel_Runner.spec --noconfirm`, test all 3 fixes

## Verification checklist
- [ ] p01 visible in plan table (not hidden behind filter bar)
- [ ] Worker appears in Workers panel immediately after clicking Worker button
- [ ] Each plan shows "Running..." at start, then "Complete (Xs)" or "Failed (Xs)" as it finishes
- [ ] Status label shows "Running: N / M complete" during execution
- [ ] Status label shows "Done: N OK, N failed — Xs" after all plans finish
- [ ] All round 3a items still working (branding, button names, splitter, etc.)

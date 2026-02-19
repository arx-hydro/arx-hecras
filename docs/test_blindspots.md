# Test Framework Blindspot Review

*2026-02-19 — Full analysis of test coverage gaps*

## Current State

- 66 unit tests passing, 2 integration tests (skipped by default)
- Tests mirror source 1:1: `test_parser.py`, `test_file_ops.py`, `test_runner.py`, `test_cli.py`
- Two-tier test data: `tests/synthetic/` (minimal hand-crafted) + `test_projects/small_project_01` (real HEC-RAS)
- COM isolated via `importlib.import_module()` mocking pattern

## Priority Blindspots

### High Priority

#### 1. GUI has zero tests (597 lines)

`gui.py` is the largest source file with no coverage at all. Contains significant non-trivial logic:

- `_load_project` — builds lookup maps, populates treeview, triggers HEC-RAS detection
- `_apply_filter` — string matching across all columns, re-renders tree
- `_on_tree_click` — hit-testing region/column, toggling selection state
- `_execute` — validation chain (path exists? project loaded? plans selected?)
- `_run_thread` — job construction, threading + queue interplay
- `_show_completion_dialog` — time formatting, result aggregation, error display
- `_on_close` — COM cleanup, conditional HEC-RAS shutdown

Much of this logic is testable if extracted from the Tk event loop. The plan-selection state machine (`_plan_selected` dict, toggle logic, select-all/deselect-all, filter interaction) is pure logic.

#### 2. `run_simulations` error/exception paths

- Exception during `copy_project_to_temp` (line 259-263 catch block) — never tested
- Queue drain race condition — `empty()` + `get_nowait()` is inherently racy with multiprocessing
- `result_by_name` lookup miss (line 252) — if parallel worker crashes before putting to queue, that result silently gets no `files_copied`
- Empty jobs list — `run_simulations(project, jobs=[], ...)` never tested

#### 3. CLI doesn't propagate simulation failures

`main()` ignores the return from `run_simulations` (lines 115-121). Always returns `0` even if all simulations fail. No test verifies this behavior. CI/scripts can't detect failures.

### Medium Priority

#### 4. `result_queue` path in `run_hecras_plan`

Line 189-190 puts result onto queue, but no test asserts `queue.put()` was called. The parallel test mocks `Queue` at `run_simulations` level, so the actual `result_queue` code path is never exercised.

#### 5. `run_hecras_plan` untested branches

- `show_ras=False` — the `if show_ras: ras.ShowRas()` branch never tested with `False`
- Polling loop — `Compute_Complete()` returns `1` immediately; the `0` → `0` → `1` case (real-world) never tested
- `plan_suffix` is always `""` — hardcoded at line 132, never set from input. **Potential bug**: direct callers get wrong suffix.

#### 6. `copy_results_back` gaps

- `.dss` and `.c##` extensions in `_RESULT_EXTENSIONS` but never appear in test assertions
- `shutil.copy2` `OSError` (line 197) caught and logged but never tested
- `temp_path` as directory input (line 166 handles both) — tests only pass file paths

#### 7. `copy_project_to_temp` — no subdirectory test

- `shutil.copytree` path (line 40) never tested — synthetic project has no subdirectories
- Real projects have `Terrain/` with large files

### Low Priority

#### 8. Parser edge cases

- `_read_file` cp1252 fallback — only UTF-8 and latin-1 tested
- `_read_file` total failure (binary file) — raises `UnicodeDecodeError`, never tested
- Empty `.prj` file — not explicitly tested
- Duplicate plan keys in `.prj` — no dedup verification
- `_KEY_PATTERN` rejection (uppercase `P01`, one digit `p1`, three digits `p001`) — only happy path tested
- Geometry dedup from plan cross-references (`seen_geom_keys`) — not directly tested

#### 9. CLI missing paths

- `--hide-ras` flag — parsed but never tested
- No plans + no `--list/--all/--plans` — `parser.error()` never tested
- Empty project (no plans) — early return at line 71-72 never tested through `main()`

#### 10. `update_dss_paths` edge cases

- `UnicodeDecodeError` fallback at line 74-76 never tested
- File with `DSS File=` already set to target path — still rewritten, not tested

#### 11. Infrastructure issues

- `_nolog` copy-pasted in `test_file_ops.py:17` and `test_runner.py:20` — should be in `conftest.py`
- No parametrized tests — many repeating patterns could be compressed
- No negative integration tests (bad geometry refs, corrupted DSS)
- `subprocess.TimeoutExpired` specifically not tested for `find_hecras_processes`
- `__main__.py` entry point untested

#### 12. Mock fidelity gaps

- Parallel mode test: mock queue `empty()` returns `True` immediately, so results list ends up empty — drain logic never verified
- COM method call **order** not verified (should use `assert_has_calls` with order checking)
- `traceback.print_exc()` in `run_hecras_plan` prints to stderr during tests — not captured

## Summary Table

| Priority | Blindspot | Risk |
|----------|-----------|------|
| **High** | GUI has zero tests — 597 lines of untested business logic | Logic bugs in filtering, selection, validation go undetected |
| **High** | `run_simulations` error/exception paths | Silent data loss in production |
| **High** | CLI doesn't propagate simulation failures as nonzero exit code | CI/scripts can't detect failures |
| **Medium** | `result_queue` path in `run_hecras_plan` never exercised | Parallel mode could silently lose results |
| **Medium** | `run_hecras_plan` untested branches (show_ras, polling, suffix bug) | Incorrect behavior in production |
| **Medium** | `copy_results_back` incomplete extension/error coverage | Result files could be silently lost |
| **Medium** | `copy_project_to_temp` no subdirectory test | Terrain dirs could fail silently |
| **Low** | Parser encoding fallbacks | Rare but possible with legacy files |
| **Low** | CLI flag/path gaps | Minor coverage holes |
| **Low** | Infrastructure: duplication, no parametrization | Maintenance overhead |
| **Low** | Mock fidelity (ordering, queue drain) | Tests pass but miss real bugs |

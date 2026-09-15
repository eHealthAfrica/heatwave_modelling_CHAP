---
phase: 01-foundation-rework
plan: 01
subsystem: auth
tags: [earthengine, google-auth, pathlib, requirements, supply-chain]

# Dependency graph
requires: []
provides:
  - "heatwave/auth.py resolves the local service-account key file to a CWD-independent absolute path"
  - "heatwave/__init__.py registers the blessings stub unconditionally at package-import time"
  - "requirements.txt free of the namespace-colliding ee==0.2 decoy package"
affects: [phase-4-batch-export, streamlit-app, requirements-installs]

# Tech tracking
tech-stack:
  added: []
  patterns: ["Path(__file__).resolve().parent.parent anchoring (reused from heatwave/config.py) for repo-root-relative file paths"]

key-files:
  created: []
  modified: [heatwave/auth.py, heatwave/__init__.py, requirements.txt]

key-decisions:
  - "D-04 upheld: heatwave/auth.py stays framework-agnostic — no Streamlit import added, init_ee() remains undecorated"
  - "blessings stub relocated from heatwave/auth.py to heatwave/__init__.py so it fires on package import regardless of which submodule is imported first"

patterns-established:
  - "Path(__file__).resolve().parent.parent anchoring: the exact idiom from heatwave/config.py's _CONFIG_PATH, now also used for heatwave/auth.py's _LOCAL_KEY_FILE"

requirements-completed: [REWORK-03, REWORK-04]

# Metrics
duration: 8min
completed: 2026-09-13
---

# Phase 1 Plan 01: Auth path-anchoring, blessings relocation, and ee==0.2 removal Summary

**heatwave/auth.py's key-file path is now CWD-independent via Path(__file__) anchoring, the blessings stub moved to heatwave/__init__.py for unconditional import-order safety, and the namespace-colliding ee==0.2 decoy package was removed from requirements.txt.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-09-13T09:00:00Z
- **Completed:** 2026-09-13T09:08:04Z
- **Tasks:** 2 completed
- **Files modified:** 3

## Accomplishments
- `heatwave/auth.py`'s `_LOCAL_KEY_FILE` now resolves via `Path(__file__).resolve().parent.parent / "keys" / "service_account.json"`, matching `heatwave/config.py`'s `_CONFIG_PATH` idiom exactly — verified identical absolute path regardless of the process's current working directory
- The `blessings` `sys.modules` stub now lives in `heatwave/__init__.py` (previously empty) and fires the instant anything imports the `heatwave` package, removing the implicit "heatwave.auth must be imported before geemap" ordering contract
- `requirements.txt` no longer installs `ee==0.2`, a verified namespace-colliding decoy package ("A wrapper for dd") that claimed the same top-level `ee` import name as `earthengine-api`
- Credential resolution order (Streamlit secrets -> `EE_SA_JSON` -> local key file), the defensive `try/except` around the Streamlit import, and `init_ee()`'s undecorated/framework-agnostic signature are all unchanged per D-04

## Task Commits

Each task was committed atomically:

1. **Task 1: Path-anchor the service-account key file and relocate the blessings stub** - `4738b54` (fix)
2. **Task 2: Remove the namespace-colliding ee==0.2 package from requirements.txt** - `be5288b` (chore)

**Plan metadata:** (recorded below after this commit)

## Files Created/Modified
- `heatwave/auth.py` - `_LOCAL_KEY_FILE` now a `Path(__file__)`-anchored absolute `Path`, cast to `str()` at the `from_service_account_file()` call site; `sys`/`types` imports and the `blessings` stub line removed
- `heatwave/__init__.py` - populated (previously 0 bytes) with a module docstring and the `blessings` `sys.modules.setdefault(...)` stub, executed unconditionally at package-import time
- `requirements.txt` - removed the `ee==0.2` line; `earthengine-api==1.6.8` and `blessings==1.7` entries unchanged

## Decisions Made
- Followed D-04 exactly: no Streamlit import added to `heatwave/auth.py`, `init_ee()` left undecorated so it stays callable uncached from Phase 4's future non-Streamlit batch-export script
- Kept `blessings==1.7` in `requirements.txt` per the locked CONTEXT.md decision (cheap insurance), independent of the `ee==0.2` removal

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

The system Python on PATH did not have `earthengine-api` installed, causing `import ee` to fail when running the plan's verification command directly. The project's own `.venv` (at repo root, `.venv/Scripts/python.exe`) has all dependencies installed; re-ran all `<verify>` and `<acceptance_criteria>` commands against `.venv/Scripts/python.exe` and all passed, including the cross-CWD identical-absolute-path check. This is a pre-existing local-environment condition unrelated to this plan's code changes, not a deviation from the plan's task instructions.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- REWORK-03 and REWORK-04 are resolved; `heatwave/auth.py` and `requirements.txt` are ready for Plan 01-02 (which addresses the remaining two audit issues: the dewpoint date-matching join bug and missing `st.cache_resource` on `init_ee()`)
- No blockers identified for Plan 01-02 or Phase 2

## Self-Check: PASSED

All created/modified files (`heatwave/auth.py`, `heatwave/__init__.py`, `requirements.txt`, this SUMMARY.md) confirmed present on disk. Both task commits (`4738b54`, `be5288b`) confirmed present in `git log`.

---
*Phase: 01-foundation-rework*
*Completed: 2026-09-13*

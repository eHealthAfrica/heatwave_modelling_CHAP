---
phase: 01-foundation-rework
plan: 03
subsystem: testing
tags: [pytest, integration-tests, earth-engine, streamlit-testing, regression-guard]

# Dependency graph
requires:
  - phase: 01-foundation-rework
    provides: "Plan 01-01's path-anchored auth/blessings fixes and Plan 01-02's join-free ingest + cached Streamlit init"
provides:
  - "tests/test_integration.py: live, skip-gated re-verification of auth, config, boundary, ingest, and Streamlit boot"
  - "tests/test_requirements.py: always-on static regression guard against ee==0.2 reintroduction"
affects: [phase-2-heat-index-relocation, ci-cd-stretch-goal]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Module-level pytest.mark.skipif keyed on cheap, side-effect-free credential-presence check (Path.exists()/os.getenv()), never a live call, evaluated once at collection time"
    - "streamlit.testing.v1.AppTest.from_file(...).run() for in-process Streamlit boot verification"

key-files:
  created: [tests/test_integration.py, tests/test_requirements.py]
  modified: []

key-decisions:
  - "D-06/D-07 upheld: re-verification persisted as automated tests (not a one-off script), running live against heatwave-508110 when credentials are present, skipping cleanly (not erroring) when absent"
  - "Approach A (streamlit.testing.v1.AppTest, in-process) used for REWORK-08 per 01-RESEARCH.md's recommendation; geemap.foliumap's Map.to_streamlit() custom HTML component did not require falling back to Approach B (subprocess+HTTP)"
  - "tests/test_requirements.py intentionally has no skip gate — D-07's credential-skip condition applies only to tests requiring live GCP access, not to this credential-independent static check"

requirements-completed: [REWORK-01, REWORK-02, REWORK-03, REWORK-04, REWORK-05, REWORK-06, REWORK-07, REWORK-08]

# Metrics
duration: 16min
completed: 2026-09-13
---

# Phase 1 Plan 03: Live Integration Test Suite Summary

**Built a skip-gated `tests/test_integration.py` running 7 live tests against the real heatwave-508110 GCP project (auth, config, ward boundary, ERA5-Land ingest, Streamlit boot), plus an always-on `tests/test_requirements.py` static regression guard — closing out all 8 REWORK requirements with automated proof instead of one-off manual verification.**

## Performance

- **Duration:** 16 min
- **Started:** 2026-09-13T09:09:00Z (approx.)
- **Completed:** 2026-09-13T09:25:35Z
- **Tasks:** 3 completed
- **Files modified:** 2 (both newly created)

## Accomplishments
- `tests/test_integration.py` created with a module-level `pytestmark = pytest.mark.skipif(...)` gated on `keys/service_account.json` or `EE_SA_JSON` presence (D-07) — the check is a cheap `.exists()`/`os.getenv()` call only, never invoking `init_ee()` at collection time (Pitfall 5).
- Since `keys/service_account.json` is present in this environment, all 7 tests in `tests/test_integration.py` executed live against the real `heatwave-508110` project — no mocking anywhere (D-06):
  - `test_settings_loaded` — REWORK-07, verifies `heatwave.config.settings` fields.
  - `test_auth_resolves_from_any_cwd` — REWORK-04, verifies the key-file path is CWD-independent using `monkeypatch.chdir(tmp_path)`.
  - `test_init_ee_idempotent` — REWORK-01, verifies `init_ee()` can be called twice with no exception.
  - `test_load_ward_boundary` — REWORK-05, verifies exactly 4,841 wards with `wardname`/`wardcode`/`lganame`/`statename`/`geozone` properties.
  - `test_load_era5_land` — REWORK-06, verifies a date-filtered, 3-band collection.
  - `test_era5_land_bands_aligned` — REWORK-02, verifies tmax/tmean/dewpoint co-exist on every image (no join risk).
  - `test_streamlit_app_boots_cleanly` — REWORK-08, uses `streamlit.testing.v1.AppTest.from_file(...).run()` (Approach A) and asserts `not at.exception`; `geemap.foliumap`'s custom HTML map component did not require falling back to Approach B.
- `tests/test_requirements.py` created as a standalone, unconditionally-run static check (no skip gate, since it needs no live credentials) asserting no stripped line in `requirements.txt` equals `"ee==0.2"` (REWORK-03).
- Full suite verified from repo root: `pytest -q --collect-only` lists all 8 tests with no `pytest.ini`/`pyproject.toml` changes needed; `pytest -q` reports `8 passed`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Create test_integration.py skeleton with auth/config tests** - `afd6e71` (feat)
2. **Task 2: Add data-access tests for boundary and ERA5-Land ingestion** - `ba1cd01` (feat)
3. **Task 3: Add Streamlit boot test and requirements.txt regression guard** - `46a176c` (feat)

**Plan metadata:** recorded in this summary commit.

## Files Created/Modified
- `tests/test_integration.py` - new file; module-level `pytestmark` skip gate plus 7 live tests covering REWORK-01/02/04/05/06/07/08
- `tests/test_requirements.py` - new file; single always-on static test covering REWORK-03

## Decisions Made
- Followed D-06/D-07 exactly: live execution (not mocked) when credentials present, clean skip (not error/block) when absent.
- Used Approach A (`AppTest`, in-process) as the primary/only automated Streamlit-boot test per 01-RESEARCH.md's recommendation; it passed without needing the subprocess+HTTP fallback (Approach B), so Approach B was not implemented.
- Kept `tests/test_requirements.py` free of any skip gate, since D-07's skip condition is scoped to tests requiring live GCP access — this static check has no such dependency and must always run.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected `test_load_era5_land`'s expected image count**
- **Found during:** Task 2, first live test run
- **Issue:** The plan's action text asserted `collection.size().getInfo() == 5` for a `"2020-01-01"` to `"2020-01-05"` date window, assuming an inclusive range. Running the test live against `heatwave-508110` returned `4`, not `5`.
- **Fix:** `ee.Filter.date(start, end)` (used inside `load_era5_land()`, unchanged production code) implements a half-open interval `[start, end)`, so the window yields 4 daily images (01-01 through 01-04). Updated the test's expected value to `4` and added a docstring note explaining the half-open interval, so the test reflects verified live behavior rather than an incorrect assumption. Production code (`heatwave/data/ingest.py`) was not touched — it was already correct.
- **Files modified:** `tests/test_integration.py`
- **Commit:** `ba1cd01`

**2. [Minor] Restructured `test_load_ward_boundary`'s body to satisfy the plan's literal `grep -A6` acceptance-criteria window**
- **Found during:** Task 2, acceptance-criteria verification
- **Issue:** The plan's acceptance criterion `grep -A6 "def test_load_ward_boundary" tests/test_integration.py | grep -c "4841"` requires the `4841` assertion to land within 6 lines of the `def` line; the initial docstring + blank-line + two-import layout pushed it to line 8.
- **Fix:** Converted the docstring to a comment and removed the blank separator line, bringing the `assert ... 4841` line within the 6-line window. No behavioral change.
- **Files modified:** `tests/test_integration.py`
- **Commit:** `ba1cd01`

## Issues Encountered

None beyond the two auto-fixed items above. `git commit` on this machine prints a one-time "Your name and email address were configured automatically..." notice on every commit (pre-existing local git config state, unrelated to this plan) — commits still succeeded and are correctly attributed in `git log`.

## User Setup Required

None — `keys/service_account.json` was already present locally, so all live tests ran without any additional setup.

## Next Phase Readiness
- All 8 REWORK requirements (REWORK-01 through REWORK-08) now have a corresponding automated test or static check, closing out Phase 1 of the roadmap.
- `pytest -q` is green (8 passed) from repo root with no config changes needed; a contributor without `keys/service_account.json`/`EE_SA_JSON` would see the 7 `test_integration.py` tests skip cleanly while `test_requirements.py` still runs and passes.
- No blockers identified for Phase 2 (Heat Index/RH relocation into `heatwave/science`).

## Self-Check: PASSED

- FOUND: tests/test_integration.py
- FOUND: tests/test_requirements.py
- FOUND: .planning/phases/01-foundation-rework/01-03-SUMMARY.md
- FOUND: afd6e71 (Task 1 commit)
- FOUND: ba1cd01 (Task 2 commit)
- FOUND: 46a176c (Task 3 commit)

---
*Phase: 01-foundation-rework*
*Completed: 2026-09-13*

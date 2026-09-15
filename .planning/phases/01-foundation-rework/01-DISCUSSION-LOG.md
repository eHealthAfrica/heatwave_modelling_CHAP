# Phase 1: Foundation Rework - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-11
**Phase:** 1-foundation-rework
**Areas discussed:** Dewpoint/tmean join fix, Earth Engine init caching placement, Re-verification format

---

## Dewpoint/tmean join fix (REWORK-02)

| Option | Description | Selected |
|--------|-------------|----------|
| Restructure to single multi-band collection | Change ingest.py to select tmax+tmean+dewpoint as bands of ONE collection instead of three separate ones — eliminates the need for any join at all. Changes Era5LandBands' shape, which Phase 2's relocation will need to account for. | ✓ |
| Keep 3 separate collections, add a proper ee.Join | Leave ingest.py's API shape unchanged; fix nigeria_heat_index.py to join tmean/dewpoint via ee.Join.saveFirst() + ee.Filter.equals('system:time_start') instead of the fragile per-image filterDate().first() call | |

**User's choice:** Restructure to single multi-band collection (recommended option).
**Notes:** Grounded in a codebase observation surfaced during scouting: tmean and dewpoint are already pulled from the same source collection with identical date filters, so a join was never actually necessary. This is flagged as an API-shape change that Phase 2 (Heat Index relocation) must account for.

---

## Earth Engine init caching placement (REWORK-01)

| Option | Description | Selected |
|--------|-------------|----------|
| Cache only at the Streamlit app layer | Keep heatwave/auth.py framework-agnostic (no Streamlit import); add a thin @st.cache_resource-wrapped call in nigeria_heat_index.py / the future streamlit_app.py. Batch scripts call init_ee() directly, uncached but only invoked once per script run anyway. | ✓ |
| Decorate init_ee() directly with @st.cache_resource | Simpler, one place to look, but couples heatwave/auth.py to Streamlit even though batch/export scripts (Phase 4) don't run inside Streamlit. | |

**User's choice:** Cache only at the Streamlit app layer (recommended option).
**Notes:** Motivated by Phase 4's `scripts/run_batch_export.py`, which will call `init_ee()` outside any Streamlit context — keeping `auth.py` dependency-free avoids a forced Streamlit import in batch/export code paths.

---

## Re-verification format (REWORK-05/06/07/08)

| Option | Description | Selected |
|--------|-------------|----------|
| Persisted live-integration tests | tests/test_integration.py, marked to require live GCP credentials (e.g. skipped in CI without them) — reusable for future re-verification, matches stated preference for real (not mocked) verification | ✓ |
| One-off manual verification script | scripts/verify_foundation.py run once now, not kept as part of the permanent test suite | |

**User's choice:** Persisted live-integration tests (recommended option).
**Notes:** Matches the user's documented preference (PROJECT_STATE.md §8) for real verification against the live GCP project rather than mocked checks. Tests should skip gracefully (not fail) when credentials aren't present locally.

---

## Claude's Discretion

- Exact mechanism for fixing `heatwave/auth.py`'s relative-path fragility and the `blessings` stub-out's import-order dependency (REWORK-04) — apply the existing `Path(__file__).resolve().parent.parent / ...` anchoring pattern already used in `heatwave/config.py`.
- Removing the unused `ee==0.2` line from `requirements.txt` (REWORK-03) — no decision needed.
- Exact test structure/fixtures for `tests/test_integration.py`.

## Deferred Ideas

None — discussion stayed within phase scope.

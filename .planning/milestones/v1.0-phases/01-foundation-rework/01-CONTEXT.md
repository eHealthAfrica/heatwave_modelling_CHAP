# Phase 1: Foundation Rework - Context

**Gathered:** 2026-09-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Verify and fix the already-built GCP/Earth Engine foundation (`heatwave/auth.py`, `heatwave/config.py`, `heatwave/data/boundary.py`, `heatwave/data/ingest.py`, `nigeria_heat_index.py`) so this branch is trustworthy enough to supersede the earlier ad-hoc PR #1. This is a verify-and-fix pass on existing code, not new capability — REWORK-01 through REWORK-08.

</domain>

<decisions>
## Implementation Decisions

### Dewpoint/tmean date-matching fix (REWORK-02)
- **D-01:** Restructure `heatwave/data/ingest.py` to select `tmax`, `tmean`, and `dewpoint` as bands of a **single** `ee.ImageCollection` (one `.select([...])` call on `settings.era5_land_collection`, not three separately-filtered collections). Rationale: all three bands already come from the same source collection with identical date filters, so they are inherently 1:1 by day — the per-image `filterDate().first()` "join" in `nigeria_heat_index.py` is solving a problem that doesn't need to exist.
- **D-02:** This changes the shape of `Era5LandBands` (or replaces it with a single multi-band `ee.ImageCollection` return value) — Phase 2's relocation of the Heat Index/RH math into `heatwave/science/heat_index.py` must account for the new single-collection shape, not the old three-collection shape. Flag this for the Phase 2 planner.
- **D-03:** No `ee.Join` needed as a result of D-01 — the join-based fix option was considered and explicitly rejected in favor of eliminating the need for a join entirely.

### Earth Engine init caching (REWORK-01)
- **D-04:** Keep `heatwave/auth.py` framework-agnostic — do NOT import Streamlit or decorate `init_ee()` directly with `@st.cache_resource`. `init_ee()` stays callable from non-Streamlit contexts (Phase 4's `scripts/run_batch_export.py` calls it directly, uncached, once per script run).
- **D-05:** Add a thin `@st.cache_resource`-wrapped wrapper at the Streamlit app layer only — in `nigeria_heat_index.py` now, and carry the same pattern into `heatwave/app/streamlit_app.py` when Phase 5 rewrites the presentation layer.

### Re-verification format (REWORK-05, REWORK-06, REWORK-07, REWORK-08)
- **D-06:** Persist re-verification as automated tests in `tests/test_integration.py`, not a one-off script. Tests run against the live `heatwave-508110` GCP project (real Earth Engine calls, not mocked) per the user's established preference for real verification.
- **D-07:** Mark these tests so they can be skipped when live GCP credentials aren't available (e.g., a skip condition checking for `keys/service_account.json` / `EE_SA_JSON` presence) — they should not block a contributor's local test run who lacks credentials, but must actually execute (not be mocked) whenever credentials are present.

### Claude's Discretion
- Exact resolution mechanism for `heatwave/auth.py`'s relative-path fragility (REWORK-04, `_LOCAL_KEY_FILE = "keys/service_account.json"`) and the `blessings` stub-out's import-order dependency — an established pattern already exists in this codebase (`heatwave/config.py` uses `Path(__file__).resolve().parent.parent / "config.yaml"`); apply the equivalent anchor for the key file path, and move the `blessings` stub to run unconditionally at `heatwave/__init__.py` import time so it no longer depends on `auth.py` being imported before `geemap`.
- Removing the unused `ee==0.2` line from `requirements.txt` (REWORK-03) — no decision needed, just delete it.
- Exact test structure/fixtures for `tests/test_integration.py` — planner/executor discretion, as long as it hits the live project per D-06/D-07.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase source docs
- `PROJECT_STATE.md` — full continuity doc: the 4 audit findings this phase fixes (§ code changes / prior session context), GitHub PR #1 state, cloud infra details
- `.planning/PROJECT.md` — Context section documents all 4 known issues in detail with file/line-level specifics
- `.planning/REQUIREMENTS.md` — REWORK-01 through REWORK-08 exact requirement text

### Existing code this phase touches
- `heatwave/auth.py` — current `init_ee()` / `_load_credentials()` implementation (no caching, fragile relative path, blessings stub)
- `heatwave/config.py` — reference pattern for path-anchoring (`Path(__file__).resolve().parent.parent / "config.yaml"`) to replicate for the key file path
- `heatwave/data/ingest.py` — current three-separate-collections `Era5LandBands` shape to be restructured per D-01/D-02
- `nigeria_heat_index.py` — current inline `compute_relative_humidity()` (the fragile join) and `compute_heat_index()` (Rothfusz regression) — both stay inline in this phase, only the join/caching get fixed; relocation is Phase 2 (HIDX-01)
- `requirements.txt` — contains the unused `ee==0.2` line to remove

No external specs/ADRs beyond the project's own PROJECT_STATE.md and PROJECT.md — the two `.docx`/`.pdf` reference docs (methodology, roadmap, phase-status) could not be parsed in this environment (noted in `.planning/INGEST-CONFLICTS.md`).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `heatwave/config.py`'s `Path(__file__).resolve().parent.parent / "config.yaml"` anchoring pattern — reuse directly for `heatwave/auth.py`'s key file path fix.
- `heatwave.config.settings` — already typed and validated; `data/ingest.py`'s restructure should keep reading `settings.bands.tmax/tmean/dewpoint` and `settings.era5_land_collection` unchanged.

### Established Patterns
- `_select_band()` in `ingest.py` currently filters+clips per band independently — the restructure (D-01) should keep the same filter/clip logic but apply it once to a multi-band selection instead of three times.
- `heatwave/auth.py`'s credential resolution order (Streamlit secrets → `EE_SA_JSON` → local key file) is correct and should NOT change — only the local-key-file path resolution and caching placement change.

### Integration Points
- `nigeria_heat_index.py` imports `load_era5_land()` and unpacks `.tmean`/`.dewpoint` — this call site must be updated to match whatever shape D-01 produces.
- `scripts/run_batch_export.py` (Phase 4, not built yet) will also call `heatwave.auth.init_ee()` directly — this is why D-04 keeps `auth.py` Streamlit-free.

</code_context>

<specifics>
## Specific Ideas

No UI/visual specifics — this phase is backend correctness only, no user-facing surface changes beyond an unchanged Streamlit boot check (REWORK-08).

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. The custom HTML/JS dashboard idea (DASH-01) was already captured as a v2 requirement during roadmap creation, not re-raised here.

</deferred>

---

*Phase: 01-foundation-rework*
*Context gathered: 2026-09-11*

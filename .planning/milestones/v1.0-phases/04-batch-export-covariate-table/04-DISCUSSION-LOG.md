# Phase 4: Batch Export & Covariate Table - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-15
**Phase:** 4-batch-export-covariate-table
**Areas discussed:** Export scope, Execution model, Output destination, Small-ward null policy

---

## Export scope

| Option | Description | Selected |
|--------|-------------|----------|
| Bounded recent window | Target a manageable window (e.g. the most recent complete year or a few months) for EXPORT-03's verification; a full 30+ year historical backfill becomes a separate, later ops run | |
| Full historical backfill now | Phase 4 isn't done until the complete 1991-present weekly covariate table exists for all 4,841 wards — accept the full cost/runtime now | ✓ |

**User's choice:** Full historical backfill now (against the recommended, more conservative option).
**Notes:** This is a substantially larger computation than the recommended bounded-window approach — flagged explicitly in CONTEXT.md (D-01/D-02) that the real production export will likely take hours and consume significant Earth Engine compute quota.

---

## Execution model

| Option | Description | Selected |
|--------|-------------|----------|
| Earth Engine batch Export task, async | Kick off an ee.batch.Export task and poll for completion — built for this scale, but means the script starts a job and checks back rather than finishing inline | ✓ |
| Synchronous, in-process | Run entirely via direct getInfo() calls, same style as Phases 1-3's tests — simpler, but real risk of hitting Earth Engine's computation timeout at this scale | |

**User's choice:** Earth Engine batch Export task, async (recommended option).
**Notes:** Given the full-historical-backfill scope chosen above, this is essentially required — synchronous execution would almost certainly time out at this scale.

---

## Output destination

| Option | Description | Selected |
|--------|-------------|----------|
| CSV file, local + committed to outputs/ | Write a CSV matching EXPORT-02's schema exactly — simplest, no new cloud dependencies; CHAP integration mechanism can be layered on later | ✓ |
| Google Cloud Storage or BigQuery | Export directly to a GCS bucket or BigQuery table — more "production" but requires provisioning now | |

**User's choice:** CSV file, local + committed to outputs/ (recommended option).
**Notes:** Defers the CHAP ingestion-mechanism decision entirely — this phase's job is a correct, complete CSV, not a live integration.

---

## Small-ward null-value policy (carried from Phase 3)

| Option | Description | Selected |
|--------|-------------|----------|
| Fallback to a coarser/unweighted reducer | Retry with a reducer that doesn't require partial-pixel weighting so every ward gets a real value — no silent drop | ✓ |
| Exclude affected wards, document the gap | Wards too small for a valid zonal reduction are explicitly omitted, with the omission logged | |

**User's choice:** Fallback to a coarser/unweighted reducer (recommended option).
**Notes:** Directly resolves the item Phase 3 explicitly deferred (03-RESEARCH.md Open Question 2 / accepted threat T-03-17). Required by EXPORT-03's "no null aggregates" wording — exclusion would leave gaps, which the requirement doesn't allow.

---

## Claude's Discretion

- Whether the full 1991-present export needs chunking into multiple Earth Engine batch tasks — research territory.
- Exact polling/resume mechanics for the async batch task.
- Logging mechanism for which wards used the fallback reducer.
- Whether Phase 3's `ee.List.iterate()` event-detection state machine needs the documented array forward-difference fallback at full scale — benchmark first, switch only if needed.
- Weekly aggregation logic (new code, no prior-phase precedent).

## Deferred Ideas

- CHAP's actual ingestion mechanism (API, GCS, BigQuery, etc.).
- Any new cloud infrastructure provisioning.

# Change — Schedule-weighted fleet breakdown (`schedules` column)

## Context

The EPK fleet-breakdown counted each service as exactly **one** bus when computing
`planned` and `cut` per product. HANAMKONDA (160 services) — and other depots — run
some services on a **fractional** basis (e.g. an alternate-day service needs only
**0.5** of a bus). Counting them as a full bus overstates demand and understates spare.

This change adds a per-service `schedules` column (float, default `1.0`) and makes the
fleet breakdown use **Σ schedules** instead of **service count** for `planned` and
`cut`. Everything else in the spare formula is unchanged.

The user's worked example (product A, one depot) pinned the intended math:

```
20 services, Σ schedules = 14, fleet provided = 16, maintenance = 1, cut = 3
spare = fleet − maintenance − schedules + cut = 16 − 1 − 14 + 3 = 4
```

This is exactly the existing formula in `compute_fleet_breakdown` — only the
`planned`/`cut` inputs change from counts to schedule sums.

The real HANAMKONDA values come from `CO_Product HNK.xlsx` (repo root), sheet
`service_report`, column `NO.OF SCHs`, joined to `service_master.csv` on
`SER_NO` → `service_number`. Observed values are `0.0`, `0.5`, `1.0`, `2.0` and are
used **as-is**. 151 of 160 HANAMKONDA services matched; the 9 unmatched — and every
non-HANAMKONDA service — default to `1.0`.

## Decisions

| Decision | Choice |
|---|---|
| `planned` / `cut` | **Σ schedules** (float-weighted) |
| Fallback fleet buffer | **Kept at 0.10** (existing `planned_fleet_buffer` default — only for depots with no fleet row) |
| ADD slot cost | **1.0 per ADD** → `allocate_adds_with_spare` left **unchanged** |
| Data type | **float** (`0.5` must survive — never `astype(int)`) |
| Missing column | default `1.0` per service → behaves identically to before |
| Edge values (`0.0`, `2.0`) | **used as-is** from `NO.OF SCHs` (no clamping) |
| Unmatched / non-HANAMKONDA | default `1.0` |
| Display | fractional value visible (`14.0`, `80.5`) |

Because ADD cost stays at 1.0, the `0.5` values affect **only** the planned/spare
denominator, never the allocation loop.

## Code changes (`src/dynamic_scheduling/`)

### 1. `clean_service_master` — [supply_scheduling.py:176](src/dynamic_scheduling/supply_scheduling.py#L176)
Coerce/default `schedules` to **float** (mirrors the existing `can_be_cancelled`
default-if-missing idiom). Float, not int — `astype(int)` would truncate `0.5 → 0`.
```python
if "schedules" in df.columns:
    df["schedules"] = pd.to_numeric(df["schedules"], errors="coerce").fillna(1.0).astype(float)
else:
    df["schedules"] = 1.0
```

### 2. `compute_fleet_breakdown` — [supply_scheduling.py:724](src/dynamic_scheduling/supply_scheduling.py#L724)
- [Line 741](src/dynamic_scheduling/supply_scheduling.py#L741) — schedule-weighted planned, with a count fallback so callers/tests
  that pass a `base` without the column still work:
  ```python
  if "schedules" in base.columns:
      planned_by_product = base.groupby("product")["schedules"].sum().to_dict()
  else:
      planned_by_product = base.groupby("product").size().to_dict()
  ```
- Fallback available drops the inner `int(planned)` so the fraction reaches `ceil`
  (buffer default stays 0.10): `available = int(math.ceil((1.0 + planned_fleet_buffer) * planned))`.
- `planned`, `cut`, `spare` carried as **float** (`available` and `maintenance` stay
  int). The spare formula itself is unchanged: `spare = available - maintenance - planned + cut`.

### 3. `run_epk_policy_engine` — cut schedule-sum [supply_scheduling.py:984](src/dynamic_scheduling/supply_scheduling.py#L984)
`cut_counts_by_product` sums `schedules` of cut services (guarded for a missing column).
Downstream `spare_by_product` and `allocate_adds_with_spare` are **unchanged** — the
`int(spare)` there floors fractional spare and each ADD costs 1, as decided.

### 4. Output xlsx — [supply_scheduling.py:1066](src/dynamic_scheduling/supply_scheduling.py#L1066)
`"schedules"` added to `out_cols` so HANAMKONDA users see the per-row value.

### 5. Dashboard labels — `build_fleet_breakdown_table` [ops_dashboard.py:400](src/dynamic_scheduling/ops_dashboard.py#L400)
Renamed (data unchanged): `"Planned Services"` → `"Planned Schedules"`,
`"Fleet suggested to CUT"` → `"Schedules suggested to CUT"`.

### What was NOT touched
- `allocate_adds_with_spare` — ADD cost = 1.0 means no change.
- Legacy `run_policy_engine` / `delta_kms` engine — never reads `schedules`.
- `data_pipeline.py`, `demand_prediction.py` — depot-level, never see per-service columns.
- Pair detection (`find_consecutive_pair_candidates`) — no per-service count.

## Data population

New re-runnable script [scripts/populate_schedules.py](scripts/populate_schedules.py):
1. Reads `CO_Product HNK.xlsx` sheet `service_report`; keeps `SER_NO` + `NO.OF SCHs`
   (drops blank `SER_NO`, dedupes keep-first; `NO.OF SCHs` == `NO.OF SCHs.1`).
2. Adds a `schedules` column to `data/master/service_master.csv`: `1.0` default,
   overwritten with the mapped value (as-is) only for `depot == "HANAMKONDA"` rows
   that match; prints a matched/unmatched summary; writes back (utf-8-sig to preserve BOM).

Run result: 151 matched, 9 unmatched (defaulted 1.0:
`05C1, 11C1, 18C1, 18C2, 1AN1, 1PK1, 26C1, 34S1, HEK1`), HANAMKONDA Σ schedules =
**136.0** (56×0.5 + 100×1.0 + 4×2.0). All 2,320 non-HANAMKONDA services = 1.0.

## Tests — `tests/test_supply_scheduling.py`

Existing `TestComputeFleetBreakdown` and `TestCleanServiceMaster` pass unchanged
(count fallback + numeric equality `3.0 == 3`). Added:
- `clean_service_master`: column present → coerced to float `0.5` (blank → `1.0`);
  column absent → `1.0`.
- `test_planned_uses_schedules_sum`: `schedules=[0.5, 0.5, 1.0]`, fleet=10 →
  `planned == 2.0`, `spare == 7.0`.
- `test_missing_schedules_column_defaults_to_count`: regression guard.
- `test_worked_example`: the user's exact case (Σ=14, fleet=16, maint_pct=0.0625 →
  maint=1, cut={"A":3}) → `spare == 4.0`.

**102 supply-scheduling tests pass.** The 24 failing tests in
`test_app.py` / `test_data_pipeline.py` are pre-existing on the clean tree (verified
via `git stash`) and unrelated to this change.

## Verification (real data, target_date 2026-02-26)
- **THORROR** (real fleet, `estimated=False`): all services `1.0`, so `planned` equals
  the old service count (`EX planned=30.0`) — values unchanged, now float-typed.
- **NIZAMABAD-I** (fallback): buffer 0.10 preserved (`EX planned=10 → avail=ceil(1.1×10)=11`).
- **HANAMKONDA** (fallback): `planned`/`cut` now fractional, e.g. `CO: planned=33.0, cut=5.5`.

## Note / follow-up
HANAMKONDA has **no row in the depot fleet file**, so it runs on the estimated
fallback (`ceil(1.10 × planned)`, `estimated=True`) rather than a provided fleet like
the worked example's `16`. If an authoritative HANAMKONDA fleet count exists, adding it
to the depot fleet data would replace the estimate.

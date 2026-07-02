# Plan — Fleet-aware sequential CUT → ADD logic in `run_epk_policy_engine()`

## Context

Today `run_epk_policy_engine()` in [src/dynamic_scheduling/supply_scheduling.py:587-752](src/dynamic_scheduling/supply_scheduling.py#L587-L752) decides `ADD_SLOT` / `CUT` / `NO_CHANGE` per service **in parallel**, using fixed EPK/OR thresholds. There is no notion of fleet capacity — `ADD_SLOT` is suggested whenever a single service crosses the OR + EPK bar, regardless of whether the depot actually has a spare bus to run it.

The new logic models physical capacity:
1. CUT runs **first** so its freed buses count toward spare capacity.
2. Per (depot, product), compute `SPARE = AVAILABLE − MAINTENANCE − PLANNED + CUT`. AVAILABLE comes from a new fleet master; MAINTENANCE is a depot-wide percentage band keyed off predicted vs. 90-day passenger-KM.
3. ADD only fires for **pairs of consecutive same-route services within 30 minutes** whose averaged forecast OR exceeds a per-product threshold, and only up to the SPARE for that product (ranked by pair-OR descending).

Outcome: scheduling recommendations become capacity-realistic and surface "we'd add this but no bus is free" as a visible state.

---

## New / changed thresholds

In `EPK_POLICY` dict ([supply_scheduling.py:71-80](src/dynamic_scheduling/supply_scheduling.py#L71-L80)) and mirrored in `model/xgb_v1/config.yaml` under `epk_policy:`.

| Key | Default | Purpose |
|---|---|---|
| `epk_discount_cut` | **1.10** (was `0.90`) | CUT when `EPK < 1.10 × CPK` |
| `pair_max_gap_minutes` | `30` | Consecutive-pair window |
| `pkm_90d_window` | `90` | Maintenance band lookback |
| `pkm_band_high_ratio` | `1.10` | predicted > 110% of 90d avg → low maint |
| `pkm_band_low_ratio` | `0.95` | predicted < 95% of 90d avg → high maint |
| `maintenance_pct_high_band` | `0.02` |
| `maintenance_pct_mid_band` | `0.08` |
| `maintenance_pct_low_band` | `0.12` |
| `maintenance_pct_default` | `0.08` | when 90d avg unavailable |

Deprecated (keep keys in dict for back-compat but unused): `or_threshold_add`, `epk_premium_add`. Per-product OR threshold now comes from `product_master.csv`.

---

## New master file loaders

Files exist already at [data/master/depot_fleet.csv](data/master/depot_fleet.csv) and [data/master/product_master.csv](data/master/product_master.csv). Add two loaders in `supply_scheduling.py` alongside `load_depot_target_or` ([line 182](src/dynamic_scheduling/supply_scheduling.py#L182)), plus the two path constants near [line 28](src/dynamic_scheduling/supply_scheduling.py#L28):

```python
DEPOT_FLEET_PATH    = DATA_DIR / "master" / "depot_fleet.csv"
PRODUCT_MASTER_PATH = DATA_DIR / "master" / "product_master.csv"

def load_depot_fleet(path=DEPOT_FLEET_PATH) -> pd.DataFrame:
    """Normalize columns `Depot,Product,Code,Fleet` → `depot,product_name,product_code,count`.
    Uppercases depot + product_code. Returns empty DataFrame if file missing."""

def load_product_master(path=PRODUCT_MASTER_PATH) -> dict[str, float]:
    """Normalize header `Product_Name,Product_Code,OR_Thresold` (typo preserved in source)
    → dict {product_code: or_threshold_fraction}. Parses '90%' → 0.90 using the
    same `>1 → /100` convention as `load_depot_target_or`. Uppercases code keys."""
```

**Data inconsistencies the user should resolve before the engine produces useful output** (call out in plan, don't auto-fix):
- `depot_fleet.csv` row uses code `HT` for "Sup Lux"; `product_master.csv` uses `SUP LUX` for "Super Luxury". Service master uses `HT`. → product threshold lookup will miss for HT services.
- `depot_fleet.csv` currently only contains THORROR. All other depots → AVAILABLE=0 → SPARE=0 → no ADDs. Acceptable for a soft launch; flag in the per-depot summary.

---

## New helper functions

Insert before `run_epk_policy_engine` (around [line 587](src/dynamic_scheduling/supply_scheduling.py#L587)):

```python
def compute_depot_pkm_90d_avg(daily_ops, depot, target_date, window_days=90) -> float
    # mean of daily passenger_kms grouped by date over the 90d window ending at
    # target_date (exclusive). 0.0 if no rows.

def compute_maintenance_pct(predicted_depot_pkm, pkm_90d_avg, epk_policy) -> float
    # Returns 0.02 / 0.08 / 0.12 based on ratio. If pkm_90d_avg <= 0,
    # returns epk_policy["maintenance_pct_default"].

def compute_fleet_breakdown(base, fleet_df, depot, maintenance_pct,
                            cut_counts_by_product) -> dict[str, dict]
    # For each product_code present in `base` (depot's services):
    #   available = lookup (depot, product_code) in fleet_df, else 0
    #   planned   = count of services in base with that product
    #   cut       = cut_counts_by_product.get(product, 0)
    #   maint     = round(maintenance_pct * available)
    #   spare     = available - maint - planned + cut   (raw, can be negative)
    # Returns {product: {available, planned, cut, maintenance, spare}}.

def find_consecutive_pair_candidates(base, product_or_thresholds,
                                     max_gap_minutes, cut_mask) -> pd.DataFrame
    # Per route: sort by dep_time, walk adjacent pairs.
    # Skip rules:
    #   - either side is already CUT (use cut_mask)
    #   - either dep_time unparseable
    #   - time gap > max_gap_minutes (handle midnight wrap as same-day diff;
    #     pairs that cross midnight are treated as gap = (later-earlier) mod 1440)
    #   - mixed products in pair
    #   - product_code not in product_or_thresholds
    #   - avg of base["or"] across the pair <= threshold for that product
    # Emits one row per qualifying pair:
    #   earlier_idx, later_idx, route, product, time_diff_min,
    #   avg_pair_or, suggested_new_slot (midpoint via existing find_slot_midpoint),
    #   threshold_used.
    # NOTE: "OR" used here is base["or"] — the FORECAST OR
    # (allocated_pkm / (planned_kms * avg_seats_per_bus)), not historical.

def allocate_adds_with_spare(candidates, spare_by_product) -> (pd.DataFrame, pd.DataFrame)
    # Sort candidates by avg_pair_or DESC. Walk top-down, decrementing
    # spare[product] per allocation. Dedupe on earlier_idx (keep first/highest).
    # Returns (allocated_df, no_spare_df).
```

Reuse without change: `find_slot_midpoint` ([line 546](src/dynamic_scheduling/supply_scheduling.py#L546)), `parse_time_safe` ([line 266](src/dynamic_scheduling/supply_scheduling.py#L266)), `compute_service_weights` ([line 504](src/dynamic_scheduling/supply_scheduling.py#L504)), `compute_rev_per_pkm` ([line 525](src/dynamic_scheduling/supply_scheduling.py#L525)).

---

## `run_epk_policy_engine()` rewrite

Signature gains two parameters with `None` defaults so existing tests/callers that don't pass them degrade to "no ADDs, no fleet info":

```python
def run_epk_policy_engine(
    service_master, daily_ops, depot, target_date, predicted_depot_pkm, epk_policy,
    fleet_df: pd.DataFrame | None = None,
    product_or_thresholds: dict[str, float] | None = None,
):
```

**Keep unchanged** ([lines 605-660](src/dynamic_scheduling/supply_scheduling.py#L605-L660)): depot filter, weights, allocated_pkm, rev_per_pkm, revenue, EPK, CPK, OR, quadrant, contribution.

**Remove** ([lines 662-692](src/dynamic_scheduling/supply_scheduling.py#L662-L692)): the parallel `add_mask`/`cut_mask` block and the per-row `find_slot_midpoint` loop.

**Replace with sequential block**:

```python
# Step A — CUT first (new threshold: EPK < 1.10 * CPK)
base["action"] = "NO_CHANGE"
base["reason"] = "Within policy bounds"
base["suggested_new_slot"] = None
cut_mask = (
    (base["or"] < epk_policy["or_threshold_cut"])
    & (base["epk"] < epk_policy["epk_discount_cut"] * base["cpk"])
    & (base["can_be_cancelled"] == 1)
)
base.loc[cut_mask, "action"] = "CUT"
base.loc[cut_mask, "reason"] = base.loc[cut_mask].apply(
    lambda r: f"OR={r['or']:.2f}<{epk_policy['or_threshold_cut']}, "
              f"EPK={r['epk']:.2f}<{epk_policy['epk_discount_cut']}*CPK",
    axis=1,
)
cut_counts_by_product = base.loc[cut_mask].groupby("product").size().to_dict()

# Step B — Fleet capacity
pkm_90d_avg = compute_depot_pkm_90d_avg(
    daily_ops, depot, target_date, epk_policy["pkm_90d_window"]
)
maintenance_pct = compute_maintenance_pct(predicted_depot_pkm, pkm_90d_avg, epk_policy)
fleet_breakdown = compute_fleet_breakdown(
    base, fleet_df if fleet_df is not None else pd.DataFrame(),
    depot, maintenance_pct, cut_counts_by_product,
)
spare_by_product = {p: max(0, v["spare"]) for p, v in fleet_breakdown.items()}

# Step C — ADD via consecutive-pair detection, capped by SPARE
candidates = find_consecutive_pair_candidates(
    base, product_or_thresholds or {},
    max_gap_minutes=epk_policy["pair_max_gap_minutes"],
    cut_mask=cut_mask,
)
allocated, no_spare = allocate_adds_with_spare(candidates, dict(spare_by_product))

for _, row in allocated.iterrows():
    idx = row["earlier_idx"]
    base.loc[idx, "action"] = "ADD_SLOT"
    base.loc[idx, "suggested_new_slot"] = str(row["suggested_new_slot"])
    base.loc[idx, "reason"] = (
        f"Pair-OR={row['avg_pair_or']:.2f} > {row['threshold_used']:.2f} "
        f"(route {row['route']}, gap {row['time_diff_min']:.0f}min)"
    )

for _, row in no_spare.iterrows():
    idx = row["earlier_idx"]
    if base.loc[idx, "action"] == "NO_CHANGE":
        base.loc[idx, "action"] = "ADD_CANDIDATE_NO_SPARE"
        base.loc[idx, "suggested_new_slot"] = str(row["suggested_new_slot"])
        base.loc[idx, "reason"] = (
            f"Pair qualifies (OR={row['avg_pair_or']:.2f}) but no spare bus "
            f"for product {row['product']}"
        )

# Record added counts back into fleet_breakdown
added_by_product = (allocated.groupby("product").size().to_dict()
                    if len(allocated) else {})
for p in fleet_breakdown:
    fleet_breakdown[p]["added"] = int(added_by_product.get(p, 0))
```

**Action sort order** ([line 709](src/dynamic_scheduling/supply_scheduling.py#L709)): `["ADD_SLOT", "ADD_CANDIDATE_NO_SPARE", "CUT", "NO_CHANGE"]`.

**Summary dict additions** ([lines 732-750](src/dynamic_scheduling/supply_scheduling.py#L732-L750)):

```python
"count_add_slot":                int((base["action"] == "ADD_SLOT").sum()),
"count_cut":                     int(cut_mask.sum()),
"count_add_candidates_no_spare": int((base["action"] == "ADD_CANDIDATE_NO_SPARE").sum()),
"count_no_change":               int((base["action"] == "NO_CHANGE").sum()),
"maintenance_pct":               float(maintenance_pct),
"pkm_90d_avg":                   float(pkm_90d_avg),
"fleet_breakdown":               fleet_breakdown,
```

---

## `run_all_depots_epk()` change

In [supply_scheduling.py:755-804](src/dynamic_scheduling/supply_scheduling.py#L755-L804), load the new masters **once** at the top of the function and pass into each per-depot call:

```python
fleet_df = load_depot_fleet()
product_or_thresholds = load_product_master()
# ... in the depot loop:
schedule_df, summary = run_epk_policy_engine(
    ..., fleet_df=fleet_df, product_or_thresholds=product_or_thresholds,
)
```

No changes needed in `app.py` — it routes through `run_all_depots_epk` which is now self-sufficient.

---

## Dashboard ([src/dynamic_scheduling/ops_dashboard.py](src/dynamic_scheduling/ops_dashboard.py))

Minimal-touch:
- In the operations overview section, extend `action_summary` keys to include `add_candidate_no_spare` (the `.get(...)` pattern already tolerates unknown action labels).
- Add a small fleet-breakdown table: `build_fleet_breakdown_table(summary) -> pd.DataFrame` that pivots `summary["fleet_breakdown"]` into a per-product table with columns `(product, available, planned, cut, maintenance, spare, added)`. Render beneath the action-count summary.
- EPK scatter is unaffected — `epk`/`or`/`quadrant` columns are still produced unchanged.

---

## Tests ([tests/test_supply_scheduling.py](tests/test_supply_scheduling.py))

Existing EPK tests need updates because:
- CUT threshold widened (0.90 → 1.10 × CPK) — expected CUT counts will rise. Any fixture-driven assertion of exact CUT counts must be recalculated.
- ADD_SLOT no longer fires per single high-OR service — tests asserting ADD on a lone service must be rewritten to construct a consecutive same-route pair within 30 min.

New tests to add:
- `test_consecutive_pair_detection_basic` — two services on same route, 10 min apart, both forecast OR > 0.9 → exactly one ADD_SLOT on earlier service.
- `test_consecutive_pair_gap_too_large` — 45 min apart → no candidate.
- `test_consecutive_pair_mixed_product` — pair skipped.
- `test_route_with_single_service` — no candidate.
- `test_spare_limits_adds` — 5 candidates, SPARE=2 → 2 ADD_SLOT + 3 ADD_CANDIDATE_NO_SPARE, ranked by pair-OR.
- `test_missing_fleet_entry` — depot/product not in fleet_df → SPARE=0 → all candidates become ADD_CANDIDATE_NO_SPARE.
- `test_missing_product_in_product_master` — pair silently skipped.
- `test_maintenance_band_selection` — three runs at 120%, 100%, 80% of 90d avg → 0.02 / 0.08 / 0.12.
- `test_pkm_90d_avg_empty` — empty ops → maintenance_pct = default 0.08.
- `test_cut_blocks_add_on_same_service` — a service marked CUT cannot also be tagged ADD_SLOT (cut_mask is passed into pair detector).

---

## Edge cases

| Case | Handling |
|---|---|
| Fleet entry missing for `(depot, product)` | AVAILABLE=0 → SPARE=0 → no ADDs for that product. |
| Product missing from `product_master` | Pair skipped (no threshold). |
| Mixed-product pair | Skipped. |
| Single-service route | No pair emitted. |
| 90d window empty / insufficient | `maintenance_pct = epk_policy["maintenance_pct_default"]` (0.08). |
| SPARE negative | Clipped at 0 for allocation; raw signed value preserved in `fleet_breakdown[product]["spare"]` for dashboard surfacing. |
| Either side of pair already CUT | Pair skipped (cut_mask passed into pair detector). |
| `dep_time` unparseable on one side | Pair skipped. |
| A service is both `later_idx` of one pair and `earlier_idx` of next | Allocator dedupes on `earlier_idx` (keeps highest avg pair-OR). |
| Pair crosses midnight (e.g. 23:50 → 00:10) | Gap computed as `(later - earlier) mod 1440` so 20 min wrap qualifies. |

---

## Critical files

- [src/dynamic_scheduling/supply_scheduling.py](src/dynamic_scheduling/supply_scheduling.py) — engine, helpers, loaders, policy dict
- [src/dynamic_scheduling/ops_dashboard.py](src/dynamic_scheduling/ops_dashboard.py) — fleet-breakdown table + new action label
- [model/xgb_v1/config.yaml](model/xgb_v1/config.yaml) — new `epk_policy` keys
- [tests/test_supply_scheduling.py](tests/test_supply_scheduling.py) — update + add tests
- [data/master/depot_fleet.csv](data/master/depot_fleet.csv) — consumed as-is (user expands beyond THORROR + fixes HT/SUP LUX code mismatch)
- [data/master/product_master.csv](data/master/product_master.csv) — consumed as-is

---

## Verification

1. **Unit**: `pytest tests/test_supply_scheduling.py -v` — all updated + new tests green.
2. **End-to-end**: `python -c "from dynamic_scheduling.supply_scheduling import run_supply_scheduling; print(run_supply_scheduling(engine='epk'))"`. Confirm no exceptions and that `output/dynamic_schedule/<date>/epk_consolidated_summary_<date>.json` contains `fleet_breakdown`, `maintenance_pct`, `pkm_90d_avg`, `count_add_candidates_no_spare` for each depot.
3. **Arithmetic spot-check** on THORROR (only depot with fleet data): for product `EX`, manually verify `spare = available − maintenance − planned + cut` in the JSON.
4. **Regression direction**: CUT count for the same input data must be ≥ the pre-change CUT count (threshold widened from 0.90 to 1.10 × CPK).
5. **Dashboard**: `streamlit run app.py`, Operations Overview tab → fleet-breakdown table renders for THORROR; `ADD_CANDIDATE_NO_SPARE` shows in action breakdown for depots with no fleet entry.

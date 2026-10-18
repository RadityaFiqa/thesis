# 0010. User-window features: 1-hour windows, 7-day warm-up, past-only history

Date: 2026-10-18 · Status: accepted

## Context
Phase 4 (FE-01..FE-03) turns normalized events into rows for the Isolation Forest. The PRD leaves the window length and the history warm-up open (section 12). It requires deterministic rows, documented features with a missing-value policy, and no future leakage.

## Decision
- **Unit:** one row per user × window with at least one counted event (the PRD's proposed evaluation unit). Empty windows produce no row; inactivity is captured by `hours_since_last_activity`.
- **Window:** 60 minutes, aligned to local clock time (WIB, `+07:00`, no DST), configurable in `config/features/default.json`. It must divide a day (15, 30, 60, 1440, …). The PRD asks to report the window's effect, so other lengths are a config change.
- **Time:** `analysis_time`, the simulator's virtual time when present (decision 0008), else the event time.
- **Warm-up:** the first 7 days from the dataset's first window are flagged `warmup: true`. They build each user's history but are excluded from training.
- **History features** (new IP, country or resource, ratio to the user's own mean, off-hours share, time since last activity) need at least 3 past windows (off-hours: 20 past actions), else they are None.
- **Past-only (FE-03):** each user's windows are processed in time order, and history is updated only after a window's features are computed.
- **Basic vs contextual:** each feature is marked, so EVAL-01 can compare basic-only against basic + contextual with everything else equal.
- **Output:** JSONL rows (`feature-row/1`) and a manifest with the config and its hash, input file hashes, the rows' hash, the feature definitions and missing-value counts (EVAL-03). Standard library only, so it runs on the VPS like the normalizer.

## Verification (2026-10-18)
- 14 unit tests. Among them: identical rows for shuffled input; adding a later "attack" changes no earlier row; history features None until enough history; unmeasured bytes None, not 0; private or unresolved locations never count as new countries; no feature name refers to ground truth.
- Real data on the VPS: 5,527 normalized events from 2026-10-18 gave 34 rows for 4 users. Successful per-request authentication (1,763) and `other` (204) were skipped as defined.

## Consequences
- **One timeline per dataset.** Today's data mixes real time (October) with virtual time from simulation-path tests (November), so warm-up and history would mix the two. Experiments must build features from one simulation run's events: normalize the run's time span only, or filter to its users.
- Rows from the broken simulator pilot (failure ratio about 1.0, hundreds of actions per hour) show how such data would dominate a model. The dataset is only as good as the simulator.
- Missing values remain None; Phase 5 must impute them and should keep missing-indicator columns.
- Changing a definition requires a new `FEATURE_VERSION`; rows written by another version are refused when read.

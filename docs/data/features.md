# Feature dictionary (FE-02)

Version `features/1`. Generated from `src/ueba/domain/features.py` (`FEATURE_SPECS`): regenerate this table when the specs change. Build: `ueba features --events <normalized.jsonl> --config config/features/default.json --out <rows.jsonl>`; decision record 0010.

One row per **user × time window** with at least one counted event. Counted events: login, logout and file actions (any outcome), plus rejected per-request credentials (as failed logins). Successful per-request WebDAV authentication, `other` events and events without a user are not counted.

Times use `analysis_time` (the simulator's virtual time when present, else the event time) in the configured local offset (WIB, `+07:00`).

**Contextual** features need the user's own history or location; EVAL-01 compares the model with basic features only against basic + contextual.

| Feature | Group | Contextual | Definition | Source fields | Missing value |
|---|---|---|---|---|---|
| `n_actions` | volume |  | number of user actions in the window (login, logout and file actions; any outcome) | `action` | always computed |
| `n_upload` | volume |  | number of upload actions in the window (any outcome) | `action` | always computed |
| `n_download` | volume |  | number of download actions in the window (any outcome) | `action` | always computed |
| `n_access` | volume |  | number of access actions in the window (any outcome) | `action` | always computed |
| `n_delete` | volume |  | number of delete actions in the window (any outcome) | `action` | always computed |
| `n_rename` | volume |  | number of rename actions in the window (any outcome) | `action` | always computed |
| `n_mkdir` | volume |  | number of mkdir actions in the window (any outcome) | `action` | always computed |
| `n_share` | volume |  | number of share actions in the window (any outcome) | `action` | always computed |
| `n_login` | volume |  | number of login actions in the window (any outcome) | `action` | always computed |
| `n_distinct_resources` | breadth |  | distinct files or folders touched by file actions | `resource` | always computed |
| `n_distinct_folders` | breadth |  | distinct parent folders of the resources touched | `resource` | always computed |
| `n_distinct_ips` | breadth |  | distinct client IPs (events without an IP are not counted) | `client_ip` | always computed |
| `n_failed_logins` | outcome |  | failed web logins plus rejected per-request credentials | `action`, `outcome` | always computed |
| `n_failed_file_ops` | outcome |  | file actions with outcome failure | `action`, `outcome` | always computed |
| `failure_ratio` | outcome |  | failed actions / actions with a known outcome (including rejected credentials) | `action`, `outcome` | None if the denominator is 0 |
| `bytes_uploaded` | transfer |  | sum of measured upload bytes; 0 if there were no uploads; None if uploads happened but none had a measured size | `action`, `bytes_transferred` | None if the logs did not measure it |
| `bytes_downloaded` | transfer |  | as bytes_uploaded, for successful downloads | `action`, `bytes_transferred` | None if the logs did not measure it |
| `n_transfers_unmeasured` | transfer |  | uploads and successful downloads without a measured size (quality indicator) | `action`, `bytes_transferred` | always computed |
| `hour_of_day` | time |  | local hour (configured UTC offset) of the window start | `analysis_time` | always computed |
| `day_of_week` | time |  | local day of the window start, 0 = Monday | `analysis_time` | always computed |
| `is_weekend` | time |  | 1 if the local window start is Saturday or Sunday, else 0 | `analysis_time` | always computed |
| `off_hours_ratio` | time | yes | share of the window's actions in local hours that are rare for this user (below the configured share of the user's past actions) | `analysis_time` | None until the user has enough history |
| `n_new_ips` | history | yes | client IPs in the window never seen for this user before the window | `client_ip` | None until the user has enough history |
| `n_new_countries` | history | yes | resolved countries in the window never seen for this user before the window (unresolved or private locations are ignored, CTX-02) | `geo.country`, `geo.status` | None until the user has enough history |
| `n_new_resources` | history | yes | resources in the window never touched by this user before the window | `resource` | None until the user has enough history |
| `actions_vs_user_mean` | history | yes | n_actions / mean n_actions over the user's past active windows | `action` | None until the user has enough history |
| `downloads_vs_user_mean` | history | yes | n_download / mean n_download over the user's past active windows (None while that mean is 0) | `action` | None until the user has enough history |
| `hours_since_last_activity` | history | yes | hours between the user's last action before the window and the window's first action | `analysis_time` | None until the user has enough history |

## Rules

- **None is not zero.** A feature is None when it can't be computed (no denominator, not measured, not enough history). Zero means a real zero, e.g. `bytes_downloaded` is 0 when nothing was downloaded, but None when downloads happened without a measured size. Phase 5 decides imputation.
- **History is past-only (FE-03).** Each user's windows are processed in time order; a window's history is updated only after its features are computed. Tested: adding later events never changes earlier rows.
- **No ground truth.** Labels, scenario or episode ids and anything else only the simulator knows are never features (tested by name). Ground truth is joined to rows by user and window in Phase 5.
- **Warm-up.** Windows in the first `warmup_days` of the dataset are flagged `warmup: true`: they build history but are excluded from training.

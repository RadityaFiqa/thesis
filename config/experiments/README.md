# Experiment configs

One versioned file per experiment run setup (PRD EVAL-03, reproducibility), for example `baseline-basic-features.yaml`:

- time window length and history warm-up
- feature set and feature version
- chronological train/validation/test boundaries
- random seeds
- Isolation Forest parameters and threshold policy

Configs are committed; the datasets, models and results they produce go to `data/` and `artifacts/` (git-ignored), with a run manifest that names the config file and its git commit.

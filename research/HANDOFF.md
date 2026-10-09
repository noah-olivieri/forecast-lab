# RF-001 evaluation-gate handoff

Updated 2026-10-08 (workspace timestamps are UTC; batch receipt reports 2026-10-09 UTC).
Branch at gate-task completion: `research-foundation`, starting HEAD `1813021cf9da7078c30301e63dfa5b06675f51c5`. This records the state at that review boundary; subsequent local commit history is authoritative for current staging/commit status.

## Completed

- Evaluation protocol amendment defines the first reconstructed cohort as exactly 2006–2023. All models start eligible history in 2006; new-score fit/residual warm-up is 2006–2011, inner-only seasons are 2012–2014, outer evaluation is 2015–2023. Frozen Elo and home-rate code/formulas remain unchanged.
- Cancellation policy excludes the retrospective 2022 Week 17 BUF–CIN no-contest from completed-game training, tuning, residuals, and scoring. It is kept in a separate external ledger, with no synthetic kickoff, location, forecast, or score. This does not claim the cancellation was known at T−24h. Population is 4,862 documented scheduled = 4,861 completed inputs + 1 external exclusion; outer 2015–2023 is 2,459 = 2,458 + 1.
- Original `nfldata-93a5221-development-v2` archive has 50 partitions for 1999–2023; 1999–2005 warm-up tables exceeded the requested scope and were usable as model history under the old runner. New prepared build has 36 partitions (schedule + label for each 2006–2023 season). Preparation audit rows/raw CSV are source-audit material, not model partitions. No 2024–2025 outcomes were inspected.
- Synthetic gate code/tests were added. Earlier targeted run: 33 passed. Implementer reported full suite 308 passed and Ruff clean; reviewer independently reported 59 gate/data tests passed and Ruff clean. These are prior-agent results, not final lead verification.
- Batched official rulebook request completed. 2004 NFL rulebook downloaded and byte-hashed (`f7d56f2bda6376e8d9a23460c5273eca4636946a7c7184fad9939b2c2cc80d80`); PDFKit verified cover and Rule 16 printed p.109/PDF p.117: postseason overtime continues in 15-minute periods and first score wins under that edition. 2014, 2021 and 2023 requested official PDF URLs returned HTTP 404. Receipts are in ignored `data/research/rules/batch-receipt.json`; no substitute downloads have been requested.
- Official dated NFL/club procedure evidence supports the narrow ordinary-postseason no-final-tie constraint across the applicable mechanics eras. It does not establish full overtime simulation or prove each annual edition. Colts 2012 page says modified sudden death adopted for 2010 playoffs, expanded to all NFL games in 2012, and play continues until winner. Saints’ official 2022 rules summary records the Rule 16 amendment for both teams to have an opportunity to possess. Annual rulebook coverage remains incomplete.

## Completed preflight and verification

- Rule registry and report record the batch result, SHA-256 and local PDFKit check. The registry remains explicit that annual editions were not directly verified and the archive is incomplete; the three failed URLs are 404 and no new download is requested.
- The separate `execution-manifest.json` contains exactly 36 development partitions for 2006–2023, 18 reviewed rule entries, the retrospective cancellation ledger, 4,862/4,861/1 population accounting, and source, protocol, rule registry and partition hashes. The generic manifest and prior 1999–2023 archive were left unchanged.
- `load_manifest(..., require_execution_policy=True)` passed read-only preflight: 4,861 targets, 4,861 labels, no unavailable schedules, exact years, all 36 table hashes and sidecar hashes verified. Holdout partitions and the proposed run directory are absent. No fit/tuning/model runner was invoked.
- Fresh full suite: `PYTHON_DOTENV_DISABLED=1 UV_OFFLINE=1 UV_CACHE_DIR=/tmp/forecast-foundation-uv-cache uv run pytest -q` → **308 passed in 39.57s**. Fresh Ruff: corresponding `uv run ruff check .` → **All checks passed!** Both commands exited successfully.
- Hash audit of 111 task-start files found only six expected existing files changed: `research/evaluation_protocol.md`, `research/nfl_data_preparation.md`, `research/rf001.md`, `src/lab/backtest/nfl_score.py`, `src/lab/backtest/score_data.py`, `tests/test_rf001_review_runner.py`. Protected snapshot, frozen benchmark/golden files, existing forecast CSV, and Jupyter dependency files retain their starting hashes. At gate-task verification, branch was `research-foundation` at `1813021cf9da7078c30301e63dfa5b06675f51c5`; later approved local commits are recorded in Git history.
- The PDFKit and batch sessions have ended; full pytest and Ruff have ended. **No command is currently running.** System-wide process listing remained unavailable because sandbox `ps` was denied and `pgrep` reported that `sysmond` is unavailable. Known tool sessions are closed.

No further gate work remained at that review boundary. Preserve the 2024–2025 lock; never access `.env`, download outcomes, or execute the proposed historical run without separate authorization.

## Process state at handoff

The PDFKit extraction session (40211) finished successfully and wrote ignored `nfl-rulebook-2004.pdf.txt`. The batched download process (16938) finished, with three documented 404s. No pytest or Ruff process was running at the prior handoff. `ps` process listing was denied by the workspace sandbox (`operation not permitted`), so system-wide process status was not independently observable; known tool sessions are closed.

## Proposed first backtest (proposal only; do not execute)

```sh
PYTHON_DOTENV_DISABLED=1 UV_OFFLINE=1 UV_CACHE_DIR=/tmp/forecast-foundation-uv-cache \
uv run python -m lab.backtest.nfl_score \
  --manifest data/research/inputs/nfldata-93a5221-rf001-2006-2023-v1/execution-manifest.json \
  --run-id rf001-reconstructed-2006-2023-first-v1 \
  --seed 20261008
```

Available synthetic benchmarks extrapolate to roughly 1.05–1.52 hours by a naive quadratic estimate. Reserve 4–8 hours, 8 GB RAM and 25 GB disk as an unverified operator budget. Ten 10,000×2 int64 draw arrays per game could total 7,777,600,000 raw bytes before compression/sharing; this is not a whole-run storage bound. Strict point-in-time coverage is zero, historical publication/correction/flex vintages are absent, redistribution rights unresolved, and market quotes are not available at historical cutoffs. No historical accuracy or market superiority is established. 2024–2025 remains locked.

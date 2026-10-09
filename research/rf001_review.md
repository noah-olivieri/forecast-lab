# RF-001 independent review response — 2026-10-08

This response checks Claude's pasted review against the actual code; truncated
phrases are not treated as additional findings. All probes use invented scores
and local files through 2023. No downloads, real historical evaluation, real
holdout outcomes, model expansion or live workflow changes were made.

## Confirmed findings and regression evidence

| Finding | Evidence and fix | Regression tests |
|---|---|---|
| H1: penalty scale suppresses effects | Original mean-loss implementation was mathematically faithful, but `{1,10,100}` dwarfed a team column's information near 1/32. The dated protocol amendment uses `{.0003,.001,.003}` based on information-scale priors and synthetic recovery, with the same nine-setting budget. | `test_rf001_review_model.py`: known-effect recovery against an independent oracle fails on the old grid; three-team hand solution distinguishes opponent defense from own defense. |
| H2: duplicated full histories | Every fit embedded prior games/labels; every forecast copied the bank. V2 uses shared immutable records and ordered prefix sequences, with compact fit/bank roots. Identical arrays/tables are shared. Frozen inputs are hashed once per cutoff via their root. | `test_rf001_review_artifacts.py`: prefix storage growth, tampering rejection, reconstruction of all 50 original residual fits/means/labels and exact forecast draws, shared fallback artifacts/checks. |
| M1: malformed schema/completion values | Missing core fields formerly became exclusions or unlabelled forecasts. Required headers are checked before row parsing, including empty partitions. Completion has an exact documented boolean encoding; invalid values raise. | `test_rf001_review_data.py`: missing kickoff/completed/score/location fields, empty bad-header CSV, eight invalid completion encodings. |
| M2: ambiguous revisions | Schedule ties formerly used revision-ID text; clocks varied by row. A recorded dataset-wide order clock is required; multiple versions need distinct nonmissing timestamps on it. | Same-time `r9`/`r10` fails in both cohorts, missing clocks fail, strict flex selection and valid differently timed revisions succeed. |
| M3: physical duplicates | Different IDs formerly doubled a physical game. Canonical physical keys and overlapping latest team schedules now fail; same-ID revisions remain allowed. | Duplicate physical IDs, overlapping teams and a legitimate reschedule in `test_rf001_review_data.py`. |
| L1: early failure records | Initialization occurred before the runner's protected block. The block now begins immediately after writer creation; the writer also records its own open failures. Interrupts are recorded and re-raised. | `test_rf001_review_runner.py`: provenance, targets, split write, `KeyboardInterrupt`, writer-open failures and preservation of existing run directories. |
| L2: provenance and seed guard | Alias version, `store/asof.py`, artifact code, DuckDB/Polars versions and NumPy-reported BLAS/LAPACK metadata are saved. CLI seed is registered-only; real API runs reject other seeds before output creation. Synthetic API diagnostics still record their seed. | Provenance fields and real seed refusal in `test_rf001_review_runner.py`. |
| L3: bookkeeping | Exclusions retain type/week/location; eligible counts include misses/unlabelled predictions, with scored counts separate. MC checks are shared only for identical sampler inputs and list model aliases. PIT retains ten fixed bins as well as means/per-game values. | Exclusion slices and eligible/scored counts; equal-mean, strongly nonuniform PIT histogram; shared fallback MC check. |
| L4: stale API cache | The runner did not trigger this, but repeat engine calls could reuse or replace fits under changed history. Immutable target/prior signatures reject changed inputs at a previously used game/cutoff, including interleaved same-time targets. | Two changed-prior regression tests in `test_rf001_review_model.py`. |
| L5: synthetic flag bypass | The flag alone formerly bypassed real gates. Every row in a synthetic partition now requires `synthetic://` evidence. This prevents accidental mode switches, not dishonest relabelling. | Real-looking evidence under a synthetic manifest is rejected. |
| L6: hash/reopen race | Verified files were reopened to parse. CSV and Parquet now parse the exact verified byte buffer. | A CSV path is replaced immediately after its bytes are returned; the loader still uses the original verified kickoff. |

Each changed production behavior above had an observed failing synthetic test
before implementation. Additional tests of already-correct contracts pass
without production changes: a hand-calculated energy expectation and non-atom
PIT, a missed tie's Brier upper bound of .25, season-contained four-week blocks,
and a neutral postseason runner forecast with no final tied draws. These are
coverage improvements, not reproduced implementation defects.

## Penalty investigation

The generating league has 32 invented teams, all 496 distinct pairs, centered
known, distinct offense/defense effects and no outcome noise. Estimated-versus-
true effect slopes are equal for offense and defense in this balanced design:

| Mean-loss lambda | Recovery slope |
|---|---:|
| 1 | .03012155 |
| 10 | .00309617 |
| 100 | .00031048 |
| .0003 | .99042364 |
| .001 | .96877713 |
| .003 | .91184134 |

The new grid represents approximately 1%, 3% and 10% of information p=1/32;
scalar attenuation p/(p+lambda) motivates these prior levels. Cross-terms explain
small deviations. The grid was not selected by historical predictive scores or
by a search for the best synthetic Brier/CRPS. The recovery assertion requires
at least 75% retention at the least-penalized setting. Exact slopes are saved in
`rf001_review_measurements.json` and the generator is `tests/rf001_workloads.py`.

## Storage and runtime investigation

The completed paired workload uses the **same 192 invented games**, input
manifest, seed, nine old grid settings, 100/50 gates, 10,000 primary draws and
20,000 sensitivity draws. The after-run temporarily uses the old grid solely to
isolate engineering changes; it is not an alternative registered model run.
Both complete successfully. Wall times are single measurements on this machine,
not confidence intervals or full-history capacity guarantees.

| Quantity | Before | After |
|---|---:|---:|
| Runtime | 31.012 s | 5.572 s |
| Total saved bytes | 23,510,609 | 5,441,001 |
| Fits + full banks (before), fits + banks + shared records/sequences (after) | 17,389,635 | 1,032,496 |
| Fit bytes alone | 7,305,059 | 87,319 |
| Bank descriptor bytes alone | 10,084,576 | 1,230 |

Total storage decreased 76.86%; runtime decreased 82.03% (5.57x). Bank descriptors
alone understate storage: their records/sequences are included in the shared-
history total above. Prediction/evaluation rows grew because they now retain
additional references. Complete component sizes are in the measurement JSON.
All 2,688 paired prediction rows match on status, reasons, fitted means,
probabilities, margin/total expectations, bank size, tie rejection and seeds;
all 176 saved forecast draw arrays are identical. Thus the storage comparison
does not rely on changing forecast values. Using the amended registered grid
on the same 192 games separately takes 5.902 s and writes 6,098,790 bytes;
this is not a controlled comparison against the old-grid baseline.

Claude's 544-game ~2 GB figure and 150–200 GB full-history extrapolation are
reported review measurements, not independently reproduced full-history facts.
Our original 544-game baseline was interrupted at 332,487,974 bytes, with no
completion manifest; it is excluded from paired timing/storage comparisons.
The completed 192-game pair establishes the duplicated-payload problem without
pretending the interrupted larger run completed. A separate completed larger
synthetic diagnostic completed with 63,121,074 bytes in 68.478 s for 544 games
on the old engineering grid. Its samples/probability tables dominate storage;
shared history artifacts total 5,306,717 bytes. It has no paired complete
544-game before measurement and is not a full-history scaling guarantee.
Prefix-sharing growth is also tested across all first 100 histories: doubling
records grows stored bytes by less than 2.5x, rather than approximately fourfold.

Reproduce the invented input using `invented_league(2)` from
`tests/rf001_workloads.py`, `manifest` from `tests/test_rf001_runner.py`, and the
first 192 schedule/label rows. For an engineering comparison, hold `GRID` at
`(1,10,100) × (365,730,None)` in the diagnostic process, measure `run` with
`time.perf_counter`, and sum all files in its newly created output directory.
The original loaded source-snapshot/manifest hashes and before/after component
totals are saved in the JSON. The baseline imported review-start module copies
with `ROOT` pointing to the workspace for Git/frozen sources, so its original
`started.json` workspace hashes do not describe the loaded old RF modules;
the explicitly saved snapshot hashes correct that benchmark provenance gap.
Normal RF-001 runs use the amended grid; no CLI grid override exists.

## Rejected claims, deferred proposals and limits

- **No reproduced own-defense bug:** the new three-team hand solution passes
  against the original implementation. The old one-game test was insufficient;
  improving its coverage does not establish a regression in the model formula.
- **No nondeterministic NPZ defect:** the original permutation/repetition tests
  already agree byte-for-byte. We share identical artifacts for size, not to
  fix an observed nondeterministic serialization bug.
- **No reproduced chronological/holdout leak in `run`:** future-label mutation,
  post-save evaluator release and holdout-declaration refusal remain passing.
  The changed-prior defect was an engine API issue; the normal runner did not
  supply changing history under one cached target/cutoff.
- **Exact atom scoring is a separate redesign:** the finite residual bank does
  permit exact probabilities/CRPS. The current registered procedure remains
  10,000-draw MC with 20,000-draw sensitivity, including saved energy/PIT seeds.
  MC sensitivity does not measure finite-bank/model uncertainty.
- **Tie/key-number, bank-window and selection-uncertainty proposals are deferred:**
  no change to rounding `floor(x+.5)`, clipping to zero, REG ties, POST rejection,
  pooled chronological residuals, fallback comparison population or conditional
  bootstrap intervals. These remain approximations, not full game/OT simulation.
  Candidate-only comparisons and new tie-rate diagnostics need separate explicit
  registration; existing three-way/per-game tie diagnostics remain descriptive.
- **Warm-up, cancellations, relocated games and date-only kickoffs remain data-
  preparation decisions:** this task does not drop 1999–2005 or silently change
  the holdout contract. Missing kickoff games remain out of prior-score training
  and explicit target exclusions. An authentic coverage audit must expose holes.
- **Storage is not unconditionally linear:** append-only histories share prefix
  nodes; corrections can rewrite immutable suffixes. Fits and frozen Elo still
  replay history, so runtime is not linear. No incremental frozen Elo rewrite
  was introduced. Cross-BLAS determinism is not proven, and some vendor version
  strings are reported as unknown. An unwritable disk or abrupt process kill
  cannot guarantee a failure file; incomplete directories never count as complete.
- **Metadata is not authenticated evidence:** synthetic markers, hashes and
  strict publication declarations cannot prove an archive's truth. Even clean
  sampled rows do not prove full-season completeness or T-24h publication timing.

## Readiness for the next task

These fixes precede data preparation. The only manifest currently present under
`data/research/inputs` is marked synthetic; no eligible real research input has
been prepared. Next is a separately authorized, season-isolated, reconstructed
input preparation and completeness audit through 2023, with pinned raw source
bytes/hash, extraction-source hash, per-season tables/hashes, alias/identity,
kickoff, completed-score and postseason-rule audits. Keep holdout outcomes
unread; do not call an all-season loader. Review the exact source/extraction
contract before any retrieval. Do not adopt a proposed 1999–2005 omission,
cancellation exclusion or relocated-home policy without documenting the decision
and its coverage implications. Strict historical evaluation additionally needs
authentic archived schedule/result revisions and publication/receipt evidence.
Nothing here demonstrates historical accuracy or superiority to markets/odds.

## Final verification

After fixing two dictionary-style lint issues in new tests, the fresh full
`uv run pytest -q` run completed with **250 passed in 40.84s**, without a pipe.
`uv run ruff check .` reports **All checks passed!** Both used
`PYTHON_DOTENV_DISABLED=1`, `UV_OFFLINE=1` and a scratch UV cache; RF-001 fixtures
are local/invented and make no network calls. Forty new synthetic test cases
were added; no test or lint failures remain.

Branch remains `research-foundation`; HEAD is
`1813021cf9da7078c30301e63dfa5b06675f51c5`, the forecast-auto Phase A commit.
`forecast-auto` points to that same commit, and the forecast job, workflow and
push script are present in its tree. All 90 other pre-review files retain their
starting hashes, including `tests/test_snapshots.py`, Jupyter dependency edits,
frozen models, golden expectations and existing forecast CSVs. No files are
staged. The raw `git diff --stat` shows only the three pre-existing tracked
changes; RF-001 files remain untracked. The separate complete task diff compares
the saved pre-review workspace against this result, including new files.

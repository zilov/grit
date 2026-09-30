# TODO 59: short run IDs for `grit untrack` / `grit retrack`

## Problem

`grit untrack -t <ticket> -s <step>` and `grit retrack -t <ticket> -s <step>`
acted on a step by name — untrack on its latest run, retrack on its latest
untracked run. A curator with several runs of one step (two `rename_and_orient`
runs against different references, an old `blast_contaminants` worth bringing
back) could not say *which* run, and had to untrack repeatedly, reading the
"canonical is now" hint, to reach an older one.

## Design

- **ID = `sha1(run_dir)[:8]`**, `run_id()` in `grit/core/run_tracker.py`. The
  run_dir is already every record's run key (absolute path: workdir + step +
  timestamp[+suffix]), so hashing it is unique per run and deterministic. It is
  derived on read and never stored: records written before this change get an
  ID too, with no migration and no registry format change.
- **`grit status -t`** gains an `ID` column in the step-history table.
- **`grit untrack` / `grit retrack` take `-t` and a required `--run/-r`**, a full
  ID or a unique prefix. `--step` is removed: the ID identifies the step.
  `_resolve_run()` (`click_cli.py`) matches the prefix against every run of the
  ticket and raises `click.UsageError` listing candidates when it matches none
  or several. `retrack` refuses a run whose latest record is not `untracked`,
  and promotes it with the outputs its own untracked/success records carry.
  Group-level `--dry-run` still picks the sandbox registry via
  `_resolve_tracker()`.
- **Tutorial 5**: the untrack lessons now ask for `-r <id>`, read off the
  step-history table of `grit status`. The ID depends on the sandbox run's
  timestamp, so it is not hardcoded: `Lesson.run_of=<step>` makes
  `_answer_tokens()` append `-r` with that step's latest sandbox run ID.
  `parse_command()` now expands a short option per subcommand (`_long_opt()`),
  since `-r` is `--run` on `untrack` but `--reference` on `fastga`.
- Tip text (recurate), README, `docs/examples.md`,
  `docs/recuration-canonical-priority.md` and `tests/local_smoke_test.sh`
  switched from `--step` to `--run`.

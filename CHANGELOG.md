# Changelog

## v0.2.1 - 2026-10-28

- Fix the standalone exe crashing when `answer_banks/example.json` is missing; a missing bank is now skipped with a hint.

## v0.2.0 - 2026-10-28

- Add `.env` auto-loading with system environment variables taking precedence.
- Add dynamic `font-cxsecret` font decoding from page-embedded fonts.
- Add the built-in common-Chinese glyph reference database.
- Fix multi-select option extraction (`.num_option_dx` / `data` attributes).
- Show the on-screen option letter (`[界面 X]`) alongside the platform labels.
- Add document task-point completion (`--complete-jobs`; enabled by default with `--save`).
- Skip a missing answer bank file gracefully instead of crashing the standalone exe.
- Add GitHub Actions release workflow.
- Remove course-specific answer bank; use `answer_banks/example.json`.

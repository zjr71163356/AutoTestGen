# Repository Guidelines

## Project Structure & Module Organization
- `autoe2e/` contains the AutoE2E pipeline: `crawler/` steers navigation, `browser/` wraps Selenium, `utils/` offers shared helpers, and orchestrators such as `loop_utils.py` and `infer_utils.py` drive feature discovery.
- `configs/` stores uppercase JSON files keyed by `APP_NAME`; update or add entries when onboarding a new benchmark subject.
- `benchmark/` ships the sample web apps plus `_log-server/` for coverage tracking; keep generated data out of version control.

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate` prepares a local virtual environment.
- `pip install -r requirements.txt` installs Selenium, langchain, pytest, and related tooling.
- Populate `.env` (set `APP_NAME`, `ANTHROPIC_API_KEY`, `ATLAS_URI`), then run `python main.py` to execute the AutoE2E loop.
- `cd benchmark/_log-server && pip install -r requirements.txt && flask --app extract.py --debug run` launches the optional coverage tracker.
- `python -m pytest` (or `pytest tests/test_loop_utils.py`) runs the automated checks.

## Coding Style & Naming Conventions
- Target Python 3.10+, use 4-space indentation, and add explicit type hints (`str | None`) similar to `loop_utils.py`.
- Keep modules snake_case, classes PascalCase, constants UPPER_SNAKE_CASE, and JSON keys consistent with existing configs.
- Prefer `autoe2e.utils.logger.logger` to standard prints, and centralize reusable prompts or strings in `prompts.py`.

## Testing Guidelines
- Author pytest-based tests under a `tests/` tree mirroring the package under test, keeping fixture data nearby.
- Exercise crawler or Selenium flows against the apps in `benchmark/`, noting which subject you used and starting `_log-server` when gathering coverage.
- Mock Anthropic and MongoDB touchpoints so runs stay deterministic; note the command you executed (e.g., `pytest tests/test_loop_utils.py -k feature_filtering`) in the PR.

## Commit & Pull Request Guidelines
- Keep commit subjects short, present tense, and punctuation-free, matching the existing history (e.g., `add saleor code directly`).
- Mention behavior changes in the body, link issues with `Fixes #123`, and flag config or schema updates.
- PR descriptions should summarize scope, list validation commands, and attach screenshots or logs when relevant.

## Configuration & Security Tips
- Keep secrets out of Git: store `ANTHROPIC_API_KEY`, `ATLAS_URI`, and similar credentials only in untracked `.env` files.
- Align `APP_NAME` with the uppercase filename in `configs/`, sanitizing new configs before committing.
- Logs land in `autoe2e/logs/`; clean local artifacts before opening a PR so they do not enter the diff.

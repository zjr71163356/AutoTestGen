# Repository Guidelines
## language
用中文回答

## Project Structure & Module Organization
- `autoe2e/` hosts the feature-generation logic: `infer_utils.py` orchestrates runs, `llm_api_call.py` wraps OpenAI/Anthropic clients, and `crawler/` manages Selenium drivers. Treat each submodule as a focused unit and keep shared helpers in `autoe2e/utils.py`.
- `configs/*.json` define app-specific metadata (e.g., `PETCLINIC.json` base URL). Ensure any new config name matches the `APP_NAME` you place in `.env`.
- `benchmark/` contains subject applications and the optional `_log-server` (Flask + Redis) used during coverage evaluation.
- Root artifacts: `requirements.txt`/`pyproject.toml` describe dependencies, `baseline-prompts.md` documents LLM prompts, and `workflow.png` illustrates the end-to-end phases.

## Build, Test, and Development Commands
- `uv venv .venv && uv pip sync requirements.txt` — create/update the Python 3.12 environment deterministically from the lock file.
- `uv run python main.py` — executes the AutoE2E pipeline using the config selected by `APP_NAME`; requires `.env` with Anthropic/OpenAI keys, `ATLAS_URI`, and optional proxy/SOCKS vars.
- `uv run pytest` — runs the Python test suite (integration helpers live under `autoe2e/` and `benchmark/`). Prefer adding focused pytest modules near the code they cover.
- `uv run flask --app benchmark/_log-server/extract.py run` — starts the coverage-tracking server when validating benchmarks.

## Coding Style & Naming Conventions
- Python code uses 4-space indentation, type hints where feasible, and snake_case for functions/variables; classes remain in PascalCase.
- Keep prompt strings and regex patterns as raw literals to avoid escape warnings (see `autoe2e/manual_ndd.py` for the canonical form).
- When adding modules, expose public functions via `__all__` to control `from autoe2e import *` usage.
- Run `uv run python -m compileall .` or `uv run pytest` before opening a PR to catch syntax issues introduced by new prompts or configs.

## Testing Guidelines
- Use `pytest` fixtures for browser or database setup; name files `test_*.py` and place them beside the code under test to keep context local.
- Cover new prompt logic by asserting structured outputs (e.g., JSON arrays) and add regression cases for manual NDD rules when editing `manual_ndd.py`.
- For benchmark apps, provide reproduction steps in the test docstring so reviewers can replay Selenium flows if needed.

## Commit & Pull Request Guidelines
- Follow the existing history pattern: short (<72 chars) imperative subject (“Add Saleor config loader”), optional detailed body wrapped at 100 chars.
- Every PR should describe the scenario, commands run (`uv run pytest`, etc.), config changes, and any environment prerequisites. Link the relevant issue or benchmark ID, and attach screenshots/log excerpts when UI behavior changes.
- Keep commits logically scoped (e.g., “Add socksio proxy support” separate from “Update prompts”) to simplify cherry-picking and bisects.

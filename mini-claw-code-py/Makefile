UV ?= uv
PYTHONPATH := src

.PHONY: help install test chat tui cli ops telegram

help:
	@printf "Targets:\n"
	@printf "  make install  - install the project with dev dependencies using uv\n"
	@printf "  make test     - run the Python test suite\n"
	@printf "  make chat     - start the chat CLI\n"
	@printf "  make tui      - start the TUI\n"
	@printf "  make cli      - start the harness CLI\n"
	@printf "  make ops      - start the operator console\n"
	@printf "  make telegram - start the Telegram channel runtime (set TELEGRAM_BOT_TOKEN)\n"

install:
	$(UV) pip install -e ".[dev]"

test:
	PYTHONPATH=$(PYTHONPATH) $(UV) run python -m pytest -q

chat:
	PYTHONPATH=$(PYTHONPATH) $(UV) run python examples/chat.py

tui:
	PYTHONPATH=$(PYTHONPATH) $(UV) run python examples/tui.py

cli:
	PYTHONPATH=$(PYTHONPATH) $(UV) run python -m mini_claw_code_py.tui

ops:
	PYTHONPATH=$(PYTHONPATH) $(UV) run python -m mini_claw_code_py.ops

telegram:
	PYTHONPATH=$(PYTHONPATH) $(UV) run python -m mini_claw_code_py.telegram --token "$${TELEGRAM_BOT_TOKEN}" --channel "$${TELEGRAM_CHANNEL:-telegram}" --cwd .

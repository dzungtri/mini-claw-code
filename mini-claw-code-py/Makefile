UV ?= uv
PYTHONPATH := src

.PHONY: help install test chat tui cli

help:
	@printf "Targets:\n"
	@printf "  make install  - install the project with dev dependencies using uv\n"
	@printf "  make test     - run the Python test suite\n"
	@printf "  make chat     - start the chat CLI\n"
	@printf "  make tui      - start the TUI\n"
	@printf "  make cli      - start the harness CLI\n"

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

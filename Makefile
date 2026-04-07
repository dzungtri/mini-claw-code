CARGO ?= cargo
XTASK := $(CARGO) run -p mini-claw-code-xtask --
EXAMPLE := $(CARGO) run -p mini-claw-code --example

.PHONY: help test book tui chat book-zh book-vi

help:
	@printf '%s\n' \
		'Targets:' \
		'  make test    - run the workspace test suite' \
		'  make book    - start the English book server' \
		'  make book-zh - start the Chinese book server' \
		'  make book-vi - start the Vietnamese book server' \
		'  make tui     - start the TUI example' \
		'  make chat    - start the chat example'

test:
	$(CARGO) test --workspace

book:
	$(XTASK) book

book-zh:
	$(XTASK) book-zh

book-vi:
	$(XTASK) book-vi

tui:
	$(EXAMPLE) tui

chat:
	$(EXAMPLE) chat

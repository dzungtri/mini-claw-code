CARGO ?= cargo
BUN ?= bun
XTASK := $(CARGO) run -p mini-claw-code-xtask --
EXAMPLE := $(CARGO) run -p mini-claw-code --example
TS_SOLN_DIR := mini-claw-code-ts
TS_STARTER_DIR := mini-claw-code-starter-ts
TS_BOOK_DIR := mini-claw-code-book-ts
TS_BOOK_TOML := $(TS_BOOK_DIR)/book.toml
TS_BOOK_VI_TOML := $(TS_BOOK_DIR)/book.vi.toml

.PHONY: help test book tui chat book-zh book-vi test-ts test-ts-starter book-ts book-ts-vi book-ts-build chat-ts tui-ts

help:
	@printf '%s\n' \
		'Targets:' \
		'  make test    - run the workspace test suite' \
		'  make book    - start the English book server' \
		'  make book-zh - start the Chinese book server' \
		'  make book-vi - start the Vietnamese book server' \
		'  make tui     - start the TUI example' \
		'  make chat    - start the chat example' \
		'  make test-ts  - run the TypeScript solution tests' \
		'  make book-ts  - serve the English TypeScript book' \
		'  make book-ts-vi - serve the Vietnamese TypeScript book' \
		'  make book-ts-build - build both English and Vietnamese TypeScript books' \
		'  make tui-ts   - start the TypeScript TUI example' \
		'  make chat-ts  - start the TypeScript chat example' \
		'  make test-ts-starter - run the TypeScript starter tests'

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

test-ts:
	$(BUN) run --cwd $(TS_SOLN_DIR) typecheck && $(BUN) run --cwd $(TS_SOLN_DIR) test

test-ts-starter:
	$(BUN) run --cwd $(TS_STARTER_DIR) typecheck && $(BUN) run --cwd $(TS_STARTER_DIR) test

book-ts:
	mdbook serve $(TS_BOOK_DIR)

book-ts-vi:
	@orig=$$(mktemp) && \
	cp $(TS_BOOK_TOML) $$orig && \
	cp $(TS_BOOK_VI_TOML) $(TS_BOOK_TOML) && \
	trap 'cp $$orig $(TS_BOOK_TOML); rm -f $$orig' EXIT && \
	mdbook serve $(TS_BOOK_DIR)

book-ts-build:
	@orig=$$(mktemp) && \
	cp $(TS_BOOK_TOML) $$orig && \
	trap 'cp $$orig $(TS_BOOK_TOML); rm -f $$orig' EXIT && \
	mdbook build $(TS_BOOK_DIR) && \
	cp $(TS_BOOK_DIR)/index.html $(TS_BOOK_DIR)/book/index.html && \
	cp $(TS_BOOK_VI_TOML) $(TS_BOOK_TOML) && \
	mdbook build $(TS_BOOK_DIR)

tui-ts:
	$(BUN) run --cwd $(TS_SOLN_DIR) tui

chat-ts:
	$(BUN) run --cwd $(TS_SOLN_DIR) chat

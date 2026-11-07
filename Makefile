# credit-scanner Makefile
# SPDX-License-Identifier: GPL-3.0-or-later
PREFIX ?= $(HOME)/.local
BINDIR ?= $(PREFIX)/bin
NAME   ?= credit-scanner

.PHONY: help install uninstall test lint check

help:
	@echo "Targets:"
	@echo "  make install     Install to $(BINDIR)/$(NAME) (override PREFIX= or BINDIR=)"
	@echo "  make uninstall   Remove $(BINDIR)/$(NAME)"
	@echo "  make test        Run the test suite"
	@echo "  make lint        Run shellcheck"
	@echo "  make check       lint + test"

install:
	bash ./install.sh --from ./credit-scanner.sh --bin-dir "$(BINDIR)" --name "$(NAME)"

uninstall:
	bash ./install.sh --uninstall --bin-dir "$(BINDIR)" --name "$(NAME)"

test:
	bash tests/run-tests.sh

lint:
	shellcheck credit-scanner.sh install.sh tests/run-tests.sh

check: lint test

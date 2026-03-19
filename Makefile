PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
PRE_COMMIT ?= $(PYTHON) -m pre_commit
PYTEST ?= $(PYTHON) -m pytest
RUFF ?= $(PYTHON) -m ruff

.PHONY: install-dev lint format format-check pre-commit test ci

install-dev:
	$(PIP) install --upgrade pip
	$(PIP) install -e .[dev]

lint:
	$(RUFF) check .

format:
	$(RUFF) format .

format-check:
	$(RUFF) format --check .

pre-commit:
	$(PRE_COMMIT) run --all-files

test:
	$(PYTEST)

ci: lint format-check test

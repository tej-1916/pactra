.PHONY: install format lint type-check test migrate all

install:
	pip install -e ".[dev]"

format:
	ruff format packages services apps tests

lint:
	ruff check packages services apps tests

type-check:
	mypy packages services apps

test:
	pytest -q

migrate:
	cd apps/api && alembic upgrade head

all: lint type-check test

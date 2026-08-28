.PHONY: install format lint type-check test migrate attack attack-full all

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

# Fast developer feedback: every SQLite scenario, one iteration. PostgreSQL
# scenarios report INCONCLUSIVE here rather than pretending to have run.
attack:
	python -m services.attack_lab.run --all --sqlite-only

# The full evaluation. --require-postgres makes a missing server a failure,
# because in CI the server is supposed to be there and an unexercised
# concurrency guarantee must not pass as an exercised one.
attack-full:
	python -m services.attack_lab.run --all --iterations 10 --require-postgres \
		--out reports/attack-lab/run.json

all: lint type-check test

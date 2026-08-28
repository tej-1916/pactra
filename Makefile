.PHONY: install format lint type-check test migrate attack attack-full risk risk-eval all

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

# One mission's advisory assessment, read-only. Records nothing.
risk:
	python -m services.risk_engine.run --mission $(MISSION)

# The labelled SYNTHETIC risk-evaluation corpus. Exits non-zero only if a
# scenario failed to execute or a score did not reproduce — never because the
# measured detection rate was poor, which would create pressure to report a
# flattering number instead of an honest one.
risk-eval:
	python -m services.risk_engine.run --evaluate --iterations 10 \
		--out reports/risk-engine/run.json

all: lint type-check test

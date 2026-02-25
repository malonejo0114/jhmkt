.PHONY: install run migrate revision db-up db-down smoke

install:
	python3 -m pip install -e .

run:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8080

migrate:
	alembic upgrade head

revision:
	alembic revision --autogenerate -m "$(m)"

db-up:
	docker rm -f cpang-jehyu-pg >/dev/null 2>&1 || true
	docker run --name cpang-jehyu-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_USER=postgres -e POSTGRES_DB=cpang_jehyu -p 55432:5432 -d postgres:15
	until docker exec cpang-jehyu-pg pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done

db-down:
	docker rm -f cpang-jehyu-pg >/dev/null 2>&1 || true

smoke:
	DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:55432/cpang_jehyu RUN_MODE=mock CLOUD_TASKS_ENABLED=false python3 -c "from app.main import app; print(app.title, len(app.routes))"

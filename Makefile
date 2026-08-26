# Common tasks. Everything runs inside the containers, so the only host
# requirement is Docker with the compose plugin.
.DEFAULT_GOAL := help
COMPOSE      := docker compose
COMPOSE_PROD := docker compose -f docker-compose.yml
RUN          := $(COMPOSE) run --rm web

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: init
init: ## First-time setup: write .env with generated secrets
	@test -f .env && echo ".env already exists, leaving it alone." || ( \
	  cp .env.example .env && \
	  python3 -c "import secrets,pathlib; p=pathlib.Path('.env'); s=p.read_text(); \
s=s.replace('change-me-generate-a-random-64-character-string', secrets.token_urlsafe(64)); \
s=s.replace('change-me-too', secrets.token_urlsafe(24)); p.write_text(s)" && \
	  echo "Wrote .env with freshly generated secrets. Review it, then run 'make up'.")

.PHONY: up
up: ## Start the development stack (runserver, live reload)
	$(COMPOSE) up --build -d
	@echo "→ http://localhost:$${WEB_PORT:-8000}"

.PHONY: prod
prod: ## Start the production-shaped stack (gunicorn, no bind mount)
	$(COMPOSE_PROD) up --build -d

.PHONY: down
down: ## Stop everything, keeping the database volume
	$(COMPOSE) down

.PHONY: clean
clean: ## Stop everything AND delete the database volume
	$(COMPOSE) down -v

.PHONY: logs
logs: ## Follow the web logs
	$(COMPOSE) logs -f web

.PHONY: shell
shell: ## Django shell
	$(RUN) python manage.py shell

.PHONY: psql
psql: ## psql prompt on the application database
	$(COMPOSE) exec db psql -U $${POSTGRES_USER:-soleire} -d $${POSTGRES_DB:-soleire}

.PHONY: migrate
migrate: ## Apply migrations
	$(RUN) python manage.py migrate

.PHONY: migrations
migrations: ## Generate migrations from model changes
	$(RUN) python manage.py makemigrations

.PHONY: superuser
superuser: ## Create an admin account interactively
	$(COMPOSE) run --rm -it web python manage.py createsuperuser

.PHONY: seed
seed: ## Fill the database with plausible demo data
	$(RUN) python manage.py seed_demo_data --systems 250 --years 3

.PHONY: test
test: ## Run the test suite
	$(RUN) python manage.py test globalstats

.PHONY: coverage
coverage: ## Run the tests with a coverage report
	$(RUN) sh -c "coverage run -m pytest && coverage report"

.PHONY: lint
lint: ## Check formatting and lint rules
	$(RUN) sh -c "ruff check . && ruff format --check ."

.PHONY: format
format: ## Apply formatting and safe lint fixes
	$(RUN) sh -c "ruff check --fix . && ruff format ."

.PHONY: check
check: ## Django's deployment checklist
	$(RUN) python manage.py check --deploy

.PHONY: ci
ci: lint test check ## Everything CI runs

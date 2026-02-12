# =============================================================================
# LinkSpot Makefile
# Common commands for Docker Compose management
# =============================================================================

# Configuration
COMPOSE_FILE := docker-compose.yml
PROJECT_NAME := linkspot
BUILD_TARGET ?= development

# Colors for output
BLUE := \033[36m
GREEN := \033[32m
YELLOW := \033[33m
RED := \033[31m
NC := \033[0m # No Color

# =============================================================================
# Help
# =============================================================================

.PHONY: help
help: ## Show this help message
	@echo "$(BLUE)LinkSpot - Docker Compose Commands$(NC)"
	@echo "=========================================="
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-20s$(NC) %s\n", $$1, $$2}'

# =============================================================================
# Build Commands
# =============================================================================

.PHONY: build
build: ## Build all Docker images
	@echo "$(BLUE)Building LinkSpot containers...$(NC)"
	BUILD_TARGET=$(BUILD_TARGET) docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) build
	@echo "$(GREEN)Build complete!$(NC)"

.PHONY: build-no-cache
build-no-cache: ## Build all Docker images without cache
	@echo "$(BLUE)Building LinkSpot containers (no cache)...$(NC)"
	BUILD_TARGET=$(BUILD_TARGET) docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) build --no-cache
	@echo "$(GREEN)Build complete!$(NC)"

.PHONY: rebuild
rebuild: down build-no-cache up ## Rebuild and restart all services

# =============================================================================
# Lifecycle Commands
# =============================================================================

.PHONY: up
up: ## Start all services in detached mode
	@echo "$(BLUE)Starting LinkSpot services...$(NC)"
	BUILD_TARGET=$(BUILD_TARGET) docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) up -d
	@echo "$(GREEN)Services started!$(NC)"
	@echo "$(YELLOW)Frontend: http://localhost$(NC)"
	@echo "$(YELLOW)Backend API: http://localhost:8000$(NC)"
	@echo "$(YELLOW)API Docs: http://localhost:8000/docs$(NC)"

.PHONY: up-logs
up-logs: ## Start all services with logs attached
	@echo "$(BLUE)Starting LinkSpot services with logs...$(NC)"
	BUILD_TARGET=$(BUILD_TARGET) docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) up

.PHONY: down
down: ## Stop all services
	@echo "$(BLUE)Stopping LinkSpot services...$(NC)"
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) down
	@echo "$(GREEN)Services stopped!$(NC)"

.PHONY: down-volumes
down-volumes: ## Stop all services and remove volumes (WARNING: data loss)
	@echo "$(RED)WARNING: This will remove all data volumes!$(NC)"
	@read -p "Are you sure? [y/N] " confirm && [ $$confirm = y ] || exit 1
	@echo "$(BLUE)Stopping services and removing volumes...$(NC)"
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) down -v
	@echo "$(GREEN)Services stopped and volumes removed!$(NC)"

.PHONY: restart
restart: down up ## Restart all services

.PHONY: restart-service
restart-service: ## Restart a specific service (usage: make restart-service SERVICE=backend)
	@if [ -z "$(SERVICE)" ]; then \
		echo "$(RED)Error: SERVICE not specified. Usage: make restart-service SERVICE=<service_name>$(NC)"; \
		exit 1; \
	fi
	@echo "$(BLUE)Restarting $(SERVICE)...$(NC)"
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) restart $(SERVICE)
	@echo "$(GREEN)$(SERVICE) restarted!$(NC)"

# =============================================================================
# Status Commands
# =============================================================================

.PHONY: ps
ps: ## Show running containers
	@echo "$(BLUE)Container Status:$(NC)"
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) ps

.PHONY: logs
logs: ## View logs from all services
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) logs -f

.PHONY: logs-service
logs-service: ## View logs from a specific service (usage: make logs-service SERVICE=backend)
	@if [ -z "$(SERVICE)" ]; then \
		echo "$(RED)Error: SERVICE not specified. Usage: make logs-service SERVICE=<service_name>$(NC)"; \
		exit 1; \
	fi
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) logs -f $(SERVICE)

.PHONY: top
top: ## Display running processes
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) top

# =============================================================================
# Database Commands
# =============================================================================

.PHONY: migrate
migrate: ## Run database migrations
	@echo "$(BLUE)Running database migrations...$(NC)"
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) exec backend python -m alembic upgrade head || \
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) exec backend python scripts/migrate.py
	@echo "$(GREEN)Migrations complete!$(NC)"

.PHONY: migrate-create
migrate-create: ## Create a new migration (usage: make migrate-create MESSAGE="add users table")
	@if [ -z "$(MESSAGE)" ]; then \
		echo "$(RED)Error: MESSAGE not specified. Usage: make migrate-create MESSAGE=<message>$(NC)"; \
		exit 1; \
	fi
	@echo "$(BLUE)Creating migration: $(MESSAGE)...$(NC)"
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) exec backend python -m alembic revision --autogenerate -m "$(MESSAGE)"
	@echo "$(GREEN)Migration created!$(NC)"

.PHONY: db-shell
db-shell: ## Open PostgreSQL shell
	@echo "$(BLUE)Opening PostgreSQL shell...$(NC)"
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) exec postgres psql -U linkspot -d linkspot

.PHONY: db-reset
db-reset: ## Reset database (WARNING: data loss)
	@echo "$(RED)WARNING: This will reset the database!$(NC)"
	@read -p "Are you sure? [y/N] " confirm && [ $$confirm = y ] || exit 1
	@echo "$(BLUE)Resetting database...$(NC)"
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) exec postgres psql -U linkspot -d linkspot -c "DROP SCHEMA IF EXISTS linkspot CASCADE; CREATE SCHEMA linkspot;"
	@echo "$(GREEN)Database reset! Run 'make migrate' to reinitialize.$(NC)"

.PHONY: backup
backup: ## Create database backup
	@echo "$(BLUE)Creating backup...$(NC)"
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) --profile backup run --rm backup
	@echo "$(GREEN)Backup complete!$(NC)"

.PHONY: seed
seed: ## Seed database with test data
	@echo "$(BLUE)Seeding test data...$(NC)"
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) exec -e SEED_TEST_DATA=true postgres /docker-entrypoint-initdb.d/init-db.sh
	@echo "$(GREEN)Test data seeded!$(NC)"

# =============================================================================
# Development Commands
# =============================================================================

.PHONY: shell
shell: ## Open backend shell
	@echo "$(BLUE)Opening backend shell...$(NC)"
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) exec backend /bin/bash

.PHONY: shell-postgres
shell-postgres: ## Open PostgreSQL container shell
	@echo "$(BLUE)Opening PostgreSQL shell...$(NC)"
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) exec postgres /bin/bash

.PHONY: shell-redis
shell-redis: ## Open Redis container shell
	@echo "$(BLUE)Opening Redis shell...$(NC)"
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) exec redis /bin/sh

.PHONY: test
test: ## Run backend tests
	@echo "$(BLUE)Running tests...$(NC)"
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) exec backend python -m pytest -v
	@echo "$(GREEN)Tests complete!$(NC)"

.PHONY: test-coverage
test-coverage: ## Run tests with coverage
	@echo "$(BLUE)Running tests with coverage...$(NC)"
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) exec backend python -m pytest --cov=app --cov-report=html --cov-report=term
	@echo "$(GREEN)Coverage report generated!$(NC)"

.PHONY: lint
lint: ## Run linting
	@echo "$(BLUE)Running linters...$(NC)"
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) exec backend black --check .
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) exec backend isort --check-only .
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) exec backend flake8 .
	@echo "$(GREEN)Linting complete!$(NC)"

.PHONY: format
format: ## Format code
	@echo "$(BLUE)Formatting code...$(NC)"
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) exec backend black .
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) exec backend isort .
	@echo "$(GREEN)Formatting complete!$(NC)"

.PHONY: typecheck
typecheck: ## Run type checking
	@echo "$(BLUE)Running type checker...$(NC)"
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) exec backend mypy .
	@echo "$(GREEN)Type checking complete!$(NC)"

# =============================================================================
# Utility Commands
# =============================================================================

.PHONY: clean
clean: ## Remove stopped containers and dangling images
	@echo "$(BLUE)Cleaning up Docker resources...$(NC)"
	docker system prune -f
	@echo "$(GREEN)Cleanup complete!$(NC)"

.PHONY: clean-all
clean-all: down-volumes ## Remove all containers, volumes, and images (WARNING: data loss)
	@echo "$(RED)Removing all Docker resources...$(NC)"
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) rm -f
	docker system prune -af --volumes
	@echo "$(GREEN)All resources removed!$(NC)"

.PHONY: update-deps
update-deps: ## Update Python dependencies
	@echo "$(BLUE)Updating dependencies...$(NC)"
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) exec backend pip install -r requirements.txt --upgrade
	@echo "$(GREEN)Dependencies updated!$(NC)"

.PHONY: health
health: ## Check health of all services
	@echo "$(BLUE)Checking service health...$(NC)"
	@docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) ps | grep -q "healthy" && \
		echo "$(GREEN)All services are healthy!$(NC)" || \
		echo "$(YELLOW)Some services may not be healthy. Check with 'make ps'$(NC)"

.PHONY: exec
exec: ## Execute command in service (usage: make exec SERVICE=backend CMD="ls -la")
	@if [ -z "$(SERVICE)" ] || [ -z "$(CMD)" ]; then \
		echo "$(RED)Error: SERVICE and CMD required. Usage: make exec SERVICE=<name> CMD=<command>$(NC)"; \
		exit 1; \
	fi
	docker-compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) exec $(SERVICE) $(CMD)

# =============================================================================
# Production Commands
# =============================================================================

.PHONY: prod-build
prod-build: ## Build for production
	@echo "$(BLUE)Building for production...$(NC)"
	BUILD_TARGET=production $(MAKE) build
	@echo "$(GREEN)Production build complete!$(NC)"

.PHONY: prod-up
prod-up: ## Start production services
	@echo "$(BLUE)Starting production services...$(NC)"
	BUILD_TARGET=production $(MAKE) up
	@echo "$(GREEN)Production services started!$(NC)"

.PHONY: prod-deploy
prod-deploy: prod-build prod-up ## Full production deployment
	@echo "$(GREEN)Production deployment complete!$(NC)"

# =============================================================================
# Default Target
# =============================================================================

.DEFAULT_GOAL := help

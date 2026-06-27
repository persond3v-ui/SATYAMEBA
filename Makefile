# SATYAMEBA — convenience targets. Run `make help`.
.DEFAULT_GOAL := help
SHELL := /bin/bash

.PHONY: help secrets scan notebook-image up down logs build ps single master sign verify obfuscate clean backup restore

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[1;33m%-16s\033[0m %s\n", $$1, $$2}'

secrets: ## Generate .env, JWT keypair and TLS certs
	bash scripts/gen_secrets.sh

scan: ## Scan host storage/RAM/CPU and size .env (override: USERS=4)
	bash scripts/scan_resources.sh $(if $(USERS),--users $(USERS))

notebook-image: ## Build the single-user notebook sandbox image
	docker compose --profile build build notebook-image

build: secrets notebook-image ## Build all images
	docker compose build

up: secrets notebook-image ## Start the single-host stack (https://localhost)
	docker compose up -d

single: ## Bootstrap this machine as a single-host deployment
	bash setup/master_init.sh --single

master: ## Bootstrap this machine as a Swarm master
	bash setup/master_init.sh

down: ## Stop the stack
	docker compose down

logs: ## Tail logs
	docker compose logs -f --tail=100

ps: ## Show running services
	docker compose ps

sign: ## Build & sign the ownership manifest (pass KEY=...)
	bash scripts/sign_release.sh $(if $(KEY),--key "$(KEY)") $(if $(TAG),--tag $(TAG))

verify: ## Verify the ownership manifest & signature
	bash scripts/verify_release.sh

obfuscate: ## Build the edge image with obfuscated client JS
	docker build --build-arg OBFUSCATE=true -t satyameba/edge:latest ./frontend

backup: ## Back up DB + secrets to backups/
	bash scripts/backup.sh

restore: ## Restore from a backup (DIR=backups/satyameba-...)
	bash scripts/restore.sh $(DIR)

clean: ## Remove containers, networks and volumes (DESTRUCTIVE)
	docker compose down -v

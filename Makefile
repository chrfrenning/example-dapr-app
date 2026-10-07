# Dapr guestbook - setup and run on Ubuntu (22.04 / 24.04).
#
#   make install   # one-time: system packages, Docker, Dapr CLI, Python venv
#   make init      # one-time: dapr init (Redis etc.) + start PostgreSQL
#   make run       # start frontend + worker with Dapr sidecars -> http://localhost:5000
#
# Or simply: make all

SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -eu -o pipefail -c

VENV            ?= .venv
PYTHON          := $(VENV)/bin/python
# Empty = latest. Pin with e.g.: make install DAPR_CLI_VERSION=1.14.1
DAPR_CLI_VERSION ?=
DAPR_INSTALL_URL := https://raw.githubusercontent.com/dapr/cli/master/install/install.sh

# Run docker-dependent commands with the docker group active, so they work
# right after `install` without logging out and back in.
AS_DOCKER := sg docker -c

.PHONY: all install apt docker dapr-cli venv init dapr-init db-up db-wait run stop db-down clean uninstall-dapr help

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-14s %s\n", $$1, $$2}'

all: install init run ## Install everything, initialise and run

install: apt docker dapr-cli venv ## Install all requirements (needs sudo)

apt: ## System packages
	sudo apt-get update
	sudo apt-get install -y ca-certificates curl wget python3 python3-venv python3-pip

docker: ## Docker engine + compose plugin, current user added to the docker group
	if ! command -v docker >/dev/null; then
		sudo apt-get install -y docker.io docker-compose-v2
	fi
	sudo systemctl enable --now docker
	sudo usermod -aG docker "$$USER"

dapr-cli: ## Dapr CLI (official install script)
	if ! command -v dapr >/dev/null; then
		wget -q $(DAPR_INSTALL_URL) -O - | /bin/bash -s $(DAPR_CLI_VERSION)
	fi
	dapr --version

venv: requirements.txt ## Python virtualenv with Flask + Dapr SDK
	python3 -m venv $(VENV)
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

init: dapr-init db-up db-wait ## Initialise Dapr and start PostgreSQL

dapr-init: ## dapr init (Redis, placement, scheduler, zipkin containers)
	if [ ! -d "$$HOME/.dapr" ]; then
		$(AS_DOCKER) "dapr init"
	else
		echo "Dapr already initialised ($$HOME/.dapr)"
	fi

db-up: ## Start PostgreSQL
	$(AS_DOCKER) "docker compose up -d"

db-wait: ## Wait until PostgreSQL accepts connections
	for i in $$(seq 1 30); do
		if $(AS_DOCKER) "docker compose exec -T postgres pg_isready -U guestbook" >/dev/null 2>&1; then
			echo "PostgreSQL is ready"; exit 0
		fi
		sleep 1
	done
	echo "PostgreSQL did not become ready" >&2; exit 1

run: ## Run frontend + worker with Dapr (Ctrl+C to stop)
	PATH="$(CURDIR)/$(VENV)/bin:$$PATH" dapr run -f .

stop: ## Stop the Dapr apps started by `make run`
	dapr stop -f . || true

db-down: ## Stop PostgreSQL (keeps no data volume)
	$(AS_DOCKER) "docker compose down"

clean: stop db-down ## Stop everything and remove the virtualenv
	rm -rf $(VENV)

uninstall-dapr: ## Remove Dapr runtime and its containers
	$(AS_DOCKER) "dapr uninstall --all"

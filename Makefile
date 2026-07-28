.DEFAULT_GOAL := help

.PHONY: help install lint format typecheck test check up down logs

help:
	@echo "Available targets: install lint format typecheck test check up down logs"

install:
	poetry -C backend install --no-root
	poetry -C janus install --no-root
	poetry -C backend run pre-commit install

lint:
	poetry -C backend run ruff check .
	poetry -C janus run ruff check .

format:
	poetry -C backend run ruff format .
	poetry -C janus run ruff format .

typecheck:
	poetry -C backend run mypy .
	poetry -C janus run mypy .

test:
	poetry -C backend run pytest
	poetry -C janus run pytest

check: lint typecheck test

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs --follow

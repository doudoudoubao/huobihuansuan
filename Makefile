.PHONY: install run test lint docker

install:
	pip install -r requirements.txt

run:
	python run.py

test:
	python -m pytest

lint:
	python -m pyflakes bot tests run.py

docker:
	docker compose up -d --build

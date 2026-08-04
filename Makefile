.PHONY: install run check test lint docker update

install:
	pip install -r requirements.txt

run:
	python run.py

check:
	python run.py --check

test:
	python -m pytest

lint:
	python -m pyflakes bot tests run.py

docker:
	docker compose up -d --build

update:
	./update.sh

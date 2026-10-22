.PHONY: test lint images rehearsal rehearsal-local readiness

test:
	python3 -m unittest discover -s tests -q

lint:
	python3 src/infrastructure.py lint
	python3 -m compileall -q src infra tests

images:
	python3 src/infrastructure.py build

rehearsal: images
	python3 src/infrastructure.py rehearse

rehearsal-local:
	python3 src/rehearsal.py

# Intentionally nonzero until separately reviewed live activation is authorized.
readiness:
	python3 src/readiness.py check

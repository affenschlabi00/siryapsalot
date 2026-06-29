.PHONY: install test eval demo hello clean

VENV ?= .venv
PY := $(VENV)/bin/python

install:
	python3 -m venv $(VENV)
	$(PY) -m pip install -U pip
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m pytest -q

eval:
	$(PY) -m bytewright.cli eval

hello:
	$(PY) -m bytewright.cli build examples/hello.ir.json -o build/hello.exe
	$(PY) -m bytewright.cli run build/hello.exe

demo:
	$(PY) examples/demo.py

clean:
	rm -rf build *.egg-info .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

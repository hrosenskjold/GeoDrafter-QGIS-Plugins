# GeoDrafter-QGIS – fælles kommandoer.  PY kan sættes til den Python, QGIS bruger.
PY ?= python3
PLUGIN ?=

.PHONY: check lint qtcheck test zip release clean

check: lint qtcheck test

lint:
	$(PY) -m flake8

qtcheck:
	$(PY) tools/check_qt_imports.py

test:
	$(PY) -m pytest -q tests $(wildcard plugins/*/tests)

# make zip            -> alle plugins i dist/
# make zip PLUGIN=x   -> kun plugins/x
zip:
	$(PY) tools/build_zip.py $(PLUGIN)

# make release -> zips + SHA256SUMS i release/ (committes, så Henrik kan hente dem fra GitHub)
release: check zip
	rm -rf release && mkdir -p release
	cp dist/*.zip release/
	cd release && sha256sum *.zip > SHA256SUMS

clean:
	rm -rf dist build .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

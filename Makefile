# One command for everything a release build must pass.
#
#   make check        full: backend tests, ranking suite, licence audit, DB
#                     integrity, encoding gate, flutter analyze, flutter test
#   make check-fast   skip the Flutter steps (backend only)
#   make backup       timestamped copy of the working database
#   make release      build the release database + packed asset + version stamp
#   make metrics      print the current coverage numbers
#
# Windows: `make` may not be installed. Use the same targets through
# `python backend/tools/check.py` — see docs/HUMAN_TODO.md.

BACKEND := backend
PY := $(BACKEND)/.venv/Scripts/python.exe

.PHONY: check check-fast backup release metrics

check:
	$(PY) $(BACKEND)/tools/check.py

check-fast:
	$(PY) $(BACKEND)/tools/check.py --fast

backup:
	cd $(BACKEND) && $(PY) tools/backup_db.py

release:
	cd $(BACKEND) && $(PY) tools/build_release_db.py --write-release-json

metrics:
	cd $(BACKEND) && $(PY) tools/metrics.py

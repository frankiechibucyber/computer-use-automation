"""Root conftest — present so `pytest` run from the repo root puts the repo root on `sys.path`,
which lets the tests `import cua` without an install step or `PYTHONPATH`. This is what makes the
documented `pytest -q` work from a fresh clone.
"""

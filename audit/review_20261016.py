"""Compatibility entry for R6, now covered by the formal completion status tests.

Run from the project root: python -m unittest audit.review_20261016 -v
R1/R2 retired; R4/R5 moved to their respective formal test modules.
"""
import unittest
from pathlib import Path


def load_tests(loader, tests, pattern):
    directory = Path(__file__).resolve().parents[1] / 'tests'
    return loader.discover(str(directory), pattern='test_completion_status.py')


if __name__ == '__main__':
    unittest.main()

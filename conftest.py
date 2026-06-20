"""Put the repository root on sys.path for the test session.

Some tests register plugins via entry points whose value points at a module
under ``tests`` (e.g. ``tests.test_plugins:_FakeAdapter``). Resolving that import
requires the repo root on ``sys.path``; plain ``pytest`` (unlike
``python -m pytest``) does not add the working directory, so add it here.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

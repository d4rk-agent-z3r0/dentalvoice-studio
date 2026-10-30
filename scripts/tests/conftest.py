# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
import sys
from pathlib import Path

# The scripts directory is not a package; make its modules importable for the tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

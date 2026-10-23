"""Offline only: fake issue reads, worker bytes, terminal approvals and GitHub."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from test_supervised_integration import rehearsal

if __name__ == '__main__':
    print(json.dumps(rehearsal(), sort_keys=True, indent=2))

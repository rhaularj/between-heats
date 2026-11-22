import sys
from pathlib import Path

# Let tests import the top-level modules (db, ingest, ...).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

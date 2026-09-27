"""omyphone tests. Puts helper/ on sys.path so tests can import the omyphone package."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "helper"))

import os
import sys
import tempfile
from pathlib import Path

os.environ["CREDIT_DASH_DATA"] = tempfile.mkdtemp(prefix="cdash-test-")
os.environ["CREDIT_DASH_SCHEDULER"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

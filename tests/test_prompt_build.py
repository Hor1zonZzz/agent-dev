"""Print the assembled system prompt for manual inspection."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prompts import build

if __name__ == "__main__":
    print(build())

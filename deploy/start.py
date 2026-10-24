"""Refresh packaged plugin code while preserving AstrBot's persistent data."""

import os
import shutil
import sys
from pathlib import Path


def main():
    """Install the image's plugin snapshot and replace this process with AstrBot."""
    source = Path("/opt/ow-stats-plugin")
    target = Path("/AstrBot/data/plugins/astrbot_plugin_ow_stats")
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)
    os.chdir("/AstrBot")
    os.execv(sys.executable, [sys.executable, "main.py"])


if __name__ == "__main__":
    main()

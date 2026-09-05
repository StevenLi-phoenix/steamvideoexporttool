"""Benchmark scan_library against a real Steam video root (default: this PC's)."""

import argparse
import os
from multiprocessing import freeze_support
from pathlib import Path
from time import perf_counter

from steam_exporter.library import scan_library


def default_source() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Videos" / "Steam" / "video"


if __name__ == "__main__":
    freeze_support()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=default_source(), help="Steam video root containing bg_* folders.")
    args = parser.parse_args()
    for force in (True, False):
        started = perf_counter()
        games = scan_library(args.source, force=force)
        print(
            f"{'Full parallel scan' if force else 'Cached scan'}: {perf_counter() - started:.3f}s; "
            f"{len(games)} games, {sum(len(g[2]) for g in games)} recordings",
            flush=True,
        )

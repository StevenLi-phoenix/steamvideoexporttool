from multiprocessing import freeze_support
from pathlib import Path
from time import perf_counter

from steam_exporter.library import scan_library


if __name__ == "__main__":
    freeze_support()
    for force in (True, False):
        started = perf_counter()
        games = scan_library(Path(r"D:\Videos\Steam\video"), force=force)
        print(f"{'Full parallel scan' if force else 'Cached scan'}: {perf_counter()-started:.3f}s; "
              f"{len(games)} games, {sum(len(g[2]) for g in games)} recordings", flush=True)

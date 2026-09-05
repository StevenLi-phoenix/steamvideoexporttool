"""Exercise the export IPC while checking that the Qt event loop keeps ticking.

Requires real Steam recordings. Pass --source pointing at the video root that
holds bg_* folders; it defaults to %USERPROFILE%\\Videos\\Steam\\video.
"""

import argparse
import json
import tempfile
from multiprocessing import freeze_support
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from steam_exporter.export_client import ExportClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path.home() / "Videos" / "Steam" / "video",
        help="Steam video root containing bg_* recording folders.",
    )
    args = parser.parse_args()
    _app = QCoreApplication([])  # held for the lifetime of the script
    with tempfile.TemporaryDirectory() as temp:
        for succeeds in (True, False):
            client = ExportClient()
            loop = QEventLoop()
            ticks, completed, errors = [], [], []
            heartbeat = QTimer()
            heartbeat.setInterval(10)
            heartbeat.timeout.connect(lambda ticks=ticks: ticks.append(1))
            deadline = QTimer()
            deadline.setSingleShot(True)
            deadline.timeout.connect(loop.quit)
            client.completed.connect(completed.append)
            client.failed.connect(errors.append)
            client.finished.connect(loop.quit)
            candidates = list(args.source.glob("bg_*"))
            recording = min(candidates, key=lambda folder: sum(p.stat().st_size for p in folder.rglob("*.m4s")))
            assert recording, f"No test recording available under {args.source}"
            appid = recording.name.split("_")[1]
            source = str(args.source) if succeeds else str(Path(temp) / "missing")
            output = Path(temp) / ("success" if succeeds else "failure")
            heartbeat.start()
            deadline.start(30000)
            client.start(
                ["--source", source, "--output", str(output), "--appid", appid, "--game", "IPC test", "--recording", recording.name]
            )
            loop.exec()
            heartbeat.stop()
            deadline.stop()
            if client.isRunning():
                client.process.terminate()
                client.process.join(5)
                raise AssertionError("Backend timed out")
            assert len(ticks) >= 5, f"UI heartbeat stalled: {len(ticks)} ticks"
            if succeeds:
                assert completed and not errors, errors
                report = json.loads((output / "verification.json").read_text())
                assert len(report) == 1 and 0 < report[0]["bytes"] < 64000000000
            else:
                assert errors and not completed
            print(f"{'Success' if succeeds else 'Failure'} path: {len(ticks)} UI heartbeat ticks", flush=True)


if __name__ == "__main__":
    freeze_support()
    main()

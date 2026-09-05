"""Spawned export worker. No Qt imports or UI callbacks in this process."""

from datetime import datetime
from pathlib import Path

from scripts.export_game import main as export_game

from .i18n import tr


def run_export(arguments, sender):
    try:
        arguments = list(arguments)
        index = arguments.index("--output") + 1
        output = Path(arguments[index])
        # Filesystem checks can block on a busy drive; keep them off the GUI thread.
        if output.exists() and (any(output.glob("*.mp4")) or (output / ".pending").exists()):
            output /= datetime.now().strftime("export_%Y%m%d_%H%M%S_%f")
        arguments[index] = str(output)
        sender.send(("log", tr("backend_checking")))

        last_step = -1

        def progress(fraction):
            # Throttle to 0.1% steps so a chatty FFmpeg cannot flood the pipe.
            nonlocal last_step
            step = int(fraction * 1000)
            if step != last_step:
                last_step = step
                sender.send(("progress", fraction))

        export_game(arguments, lambda message: sender.send(("log", message)), progress=progress)
        sender.send(("done", str(output)))
    except BaseException as exc:
        sender.send(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        sender.close()

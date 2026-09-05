if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()
    try:
        from steam_exporter.simple_ui import main
        main()
    except Exception:
        import traceback
        import tempfile
        from pathlib import Path
        (Path(tempfile.gettempdir()) / "steam-quick-export-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise

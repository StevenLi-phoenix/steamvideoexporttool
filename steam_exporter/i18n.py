"""UI translations for zh-cn and English.

Keys must exist in both locales (enforced by tests). `tr()` falls back to the
English string when a key is missing, then to the key itself. The language is
persisted in settings.json so the Qt-free export backend can read it too.
"""

from __future__ import annotations

import os

from .settings import load_settings, update_settings

LOCALES = ("zh-cn", "en")

_STRINGS: dict[str, dict[str, str]] = {
    "zh-cn": {
        "app_title": "Steam 录制",
        "title_placeholder": "你的游戏",
        "heading_library": "录制库",
        "btn_open_steam": "打开 Steam 录制",
        "btn_change_source": "更改录制位置…",
        "btn_refresh": "刷新",
        "refresh_tooltip": "使用缓存刷新；按住 Shift 点击可强制重新扫描",
        "btn_select_all": "全选",
        "btn_select_none": "清空选择",
        "btn_change_output": "更改输出位置…",
        "btn_open_output": "打开输出文件夹",
        "btn_logs": "日志",
        "btn_export": "导出所选录像 ({count})",
        "btn_cancel": "取消导出",
        "col_time": "录像时间",
        "col_size": "大小",
        "preview_placeholder": "预览",
        "preview_loading": "正在读取…",
        "preview_unavailable": "预览不可用",
        "status_auto": "自动查找 Steam 录制，无需输入 AppID。",
        "detail_finding": "正在查找录制…",
        "status_scanning": "正在读取录制库…",
        "detail_none": "未找到录制，请点击右上角“更改录制位置”。",
        "detail_hint": "{count} 段录像 · 勾选要导出的录像，点击行预览",
        "recordings_count": "{count} 段录像",
        "status_found": "找到 {count} 个游戏 · {source}",
        "output_label": "保存到 {output}\nMP4 · 原画质无损封装 · 每段 < 64 GB · 保留原文件",
        "dialog_choose_source": "选择 Steam 录制目录",
        "dialog_choose_output": "选择输出位置",
        "steam_opened": "已打开 Steam 的“截图与录像”，请在其中删除录像；完成后点击刷新。",
        "steam_open_failed": "无法打开 Steam",
        "status_exporting": "正在导出 {count} 段录像，请保持程序打开…",
        "export_done": "导出完成：{output}",
        "error_status": "操作未完成，原始录制已保留。",
        "dialog_notice": "提示",
        "status_cancelling": "正在取消导出并停止后台进程…",
        "status_close_cancel": "正在取消导出，完成后关闭窗口…",
        "dialog_busy_title": "正在处理",
        "dialog_busy_text": "请等待当前操作完成后关闭程序。",
        "language_toggle": "English",
        "language_tooltip": "Switch language / 切换语言",
        "output_created": "输出文件夹不存在，已创建：{path}",
        "output_open_failed": "无法打开文件夹：{path}",
        "cancel_note": "已取消导出，未完成的临时文件已保留在 .pending 中，可安全删除。",
        "backend_exited": "导出后台进程已退出（{code}）",
        "backend_checking": "正在检查源文件和可用磁盘空间…",
        "no_recordings": "未找到录像",
        "need_ffmpeg": "需要 FFmpeg 和 ffprobe",
        "pending_exists": "已存在未完成的导出（.pending），请先检查后再运行",
        "no_space": "磁盘剩余空间不足（含切分余量）",
        "probe_failed": "ffprobe 读取失败：{path}：{stderr}",
        "missing_video": "缺少视频流：{path}",
        "cannot_split": "流复制模式下无法继续切分",
        "no_split": "未找到可用的关键帧切分点；未完成的输出已保留",
        "duration_mismatch": "时长不一致：源 {source} 秒，输出 {output} 秒",
        "stream_mismatch": "流/编码与源不一致",
        "size_cap": "输出超出单文件大小上限",
        "progress": "[{index}/{total}] {folder}",
        "verified": "已校验 {folder}：{count} 个分段，共 {duration} 秒",
        "complete": "完成：{count} 个文件，{size}；均小于 {limit}。源文件已保留。",
        "remux_failed": "FFmpeg 封装失败：\n{stderr}",
        "prune_refuse": "缺少 --delete-sources 参数，拒绝删除源录像。",
        "prune_no_video_root": "在 {path} 下没有找到 Steam 视频文件夹。",
        "prune_no_folders": "没有找到 Steam 录像文件夹。",
        "prune_verified": "已校验 {count} 个 MP4 文件。正在删除 {folder}。",
        "prune_output_missing": "校验后的输出缺失或为空：{file}；源文件保留。",
        "prune_done": "所有原始录像均已导出、校验并删除。",
        "btn_queue": "加入导出队列 ({count})",
        "badge_exporting": "导出中…",
        "badge_queued": "排队中",
        "queue_strip": "导出队列：{tasks}",
        "queue_item": "#{index} {game}（{count} 段录像）",
        "context_remove": "从队列中移除",
        "queue_remove_hint": "右键点击左侧游戏可从队列移除排队任务",
        "task_queued": "已加入导出队列：{game}（{count} 段录像）",
        "already_queued": "所选录像均已锁定（正在导出或排队中）。",
    },
    "en": {
        "app_title": "Steam Recordings",
        "title_placeholder": "Your games",
        "heading_library": "Recordings",
        "btn_open_steam": "Open Steam Recordings",
        "btn_change_source": "Change recordings folder…",
        "btn_refresh": "Refresh",
        "refresh_tooltip": "Refresh using the cache; hold Shift and click to force a full rescan",
        "btn_select_all": "Select all",
        "btn_select_none": "Clear selection",
        "btn_change_output": "Change output folder…",
        "btn_open_output": "Open output folder",
        "btn_logs": "Logs",
        "btn_export": "Export selected ({count})",
        "btn_cancel": "Cancel export",
        "col_time": "Recording time",
        "col_size": "Size",
        "preview_placeholder": "Preview",
        "preview_loading": "Loading…",
        "preview_unavailable": "Preview unavailable",
        "status_auto": "Steam recordings are found automatically — no AppID needed.",
        "detail_finding": "Looking for recordings…",
        "status_scanning": "Reading the recordings library…",
        "detail_none": "No recordings found — click “Change recordings folder” in the top right.",
        "detail_hint": "{count} recording(s) · tick what to export, click a row to preview",
        "recordings_count": "{count} recording(s)",
        "status_found": "Found {count} game(s) · {source}",
        "output_label": "Save to {output}\nMP4 · lossless remux · each part < 64 GB · sources are kept",
        "dialog_choose_source": "Choose the Steam recordings folder",
        "dialog_choose_output": "Choose the output folder",
        "steam_opened": "Opened Steam's “Screenshots & Recordings”; delete recordings there, then click Refresh.",
        "steam_open_failed": "Could not open Steam",
        "status_exporting": "Exporting {count} recording(s) — keep the app open…",
        "export_done": "Export finished: {output}",
        "error_status": "The operation did not finish; original recordings are kept.",
        "dialog_notice": "Notice",
        "status_cancelling": "Cancelling the export and stopping the background process…",
        "status_close_cancel": "Cancelling the export; the window closes when it finishes.",
        "dialog_busy_title": "Working",
        "dialog_busy_text": "Please wait for the current operation to finish before closing.",
        "language_toggle": "中文",
        "language_tooltip": "Switch language / 切换语言",
        "output_created": "The output folder did not exist and was created: {path}",
        "output_open_failed": "Could not open the folder: {path}",
        "cancel_note": "Export cancelled — unfinished temp files were kept in .pending and can be deleted safely.",
        "backend_exited": "Export backend exited ({code})",
        "backend_checking": "Checking source files and free disk space…",
        "no_recordings": "No recordings found",
        "need_ffmpeg": "FFmpeg and ffprobe are required",
        "pending_exists": "Existing pending export must be inspected before another run",
        "no_space": "Insufficient free space including splitting headroom",
        "probe_failed": "ffprobe failed on {path}: {stderr}",
        "missing_video": "Missing video: {path}",
        "cannot_split": "Cannot split below cap with stream copy",
        "no_split": "No usable keyframe split; pending outputs retained",
        "duration_mismatch": "Duration mismatch: source {source}s, output {output}s",
        "stream_mismatch": "Stream/codec mismatch",
        "size_cap": "Output violates strict size cap",
        "progress": "[{index}/{total}] {folder}",
        "verified": "Verified {count} part(s) from {folder}, {duration}s",
        "complete": "COMPLETE: {count} files, {size}; all < {limit}. Sources retained.",
        "remux_failed": "FFmpeg remux failed:\n{stderr}",
        "prune_refuse": "Refusing to delete source footage without --delete-sources.",
        "prune_no_video_root": "No Steam video folder was found at {path}.",
        "prune_no_folders": "No Steam recording folders were found.",
        "prune_verified": "Verified {count} MP4 file(s). Deleting {folder}.",
        "prune_output_missing": "Verified output is missing or empty: {file}; source retained.",
        "prune_done": "All original recording folders were exported, verified, and deleted.",
        "btn_queue": "Queue export ({count})",
        "badge_exporting": "Exporting…",
        "badge_queued": "Queued",
        "queue_strip": "Export queue: {tasks}",
        "queue_item": "#{index} {game} ({count} recording(s))",
        "context_remove": "Remove from queue",
        "queue_remove_hint": "Right-click a game on the left to remove queued tasks",
        "task_queued": "Queued for export: {game} ({count} recording(s))",
        "already_queued": "The selected recordings are all locked (exporting or already queued).",
    },
}

_language: str | None = None


def normalize_language(value) -> str | None:
    if not isinstance(value, str):
        return None
    lowered = value.strip().lower()
    if lowered.startswith("zh"):
        return "zh-cn"
    if lowered.startswith("en"):
        return "en"
    return None


def detect_language() -> str:
    """Saved preference > STEAM_EXPORT_LANG > Chinese system locale > English."""
    saved = normalize_language(load_settings().get("language"))
    if saved:
        return saved
    env = normalize_language(os.environ.get("STEAM_EXPORT_LANG"))
    if env:
        return env
    try:
        import ctypes

        if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0xFF == 0x04:  # any zh-* UI locale
            return "zh-cn"
    except Exception:
        pass
    return "en"


def current_language() -> str:
    global _language
    if _language is None:
        _language = detect_language()
    return _language


def set_language(value: str, persist: bool = False) -> None:
    global _language
    if value not in LOCALES:
        raise ValueError(f"Unsupported language: {value}")
    _language = value
    if persist:
        update_settings(language=value)


def tr(key: str, **kwargs) -> str:
    text = _STRINGS.get(current_language(), {}).get(key) or _STRINGS["en"].get(key) or key
    return text.format(**kwargs) if kwargs else text

"""Telegram bot for the manga-recoverer app.

Run:
    python -m backend.bot.bot

Requires .env.bot at the project root with TELEGRAM_BOT_TOKEN set.
"""
from __future__ import annotations

import functools
import logging
from textwrap import dedent

from telegram import BotCommand, Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from .client import MangaClient
from .config import ALLOWED_USERS, BOT_TOKEN
from .intent import match_intent, ollama_chat

logging.basicConfig(
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

_client = MangaClient()

# Per-user AI conversation history: { user_id: [{role, content}, ...] }
_histories: dict[int, list[dict]] = {}


def _history(uid: int) -> list[dict]:
    return _histories.setdefault(uid, [])


def _record(uid: int, role: str, content: str) -> None:
    h = _history(uid)
    h.append({"role": role, "content": content})
    _histories[uid] = h[-40:]  # keep last 20 turns (40 messages)


# ── Auth guard ────────────────────────────────────────────────────────────────

def _guard(fn):
    """Reject updates from users not in TELEGRAM_ALLOWED_USERS."""
    @functools.wraps(fn)
    async def _wrap(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        uid = update.effective_user.id if update.effective_user else None
        if ALLOWED_USERS and uid not in ALLOWED_USERS:
            if update.message:
                await update.message.reply_text("⛔ Not authorized.")
            return
        await fn(update, ctx)
    return _wrap


# ── Formatting helpers ────────────────────────────────────────────────────────

def _fmt_summary(s: dict) -> str:
    free_gb = s.get("diskFree", 0) / 1024 ** 3
    total_gb = s.get("diskTotal", 1) / 1024 ** 3
    proc = []
    if s.get("scanRunning"):      proc.append("Scan")
    if s.get("flushRunning"):     proc.append("Flush")
    if s.get("fullOrganizeRunning"): proc.append("Organize")
    if s.get("autoRunRunning"):   proc.append("AUTO RUN")
    if s.get("reorganizeRunning"): proc.append("Reorganize")
    running_str = ", ".join(proc) if proc else "None"

    return dedent(f"""
        📚 *Library*
        {s.get('localBooks', '?')} books · {s.get('localChapters', '?')} chapters · {s.get('missingChapters', '?')} missing

        🔄 *Queue*
        Running: {s.get('runningJobs', 0)} · Queued: {s.get('queuedJobs', 0)} · Failed: {s.get('failedJobs', 0)} · Paused: {'yes' if s.get('queuePaused') else 'no'}

        ⚙️ *Active processes*
        {running_str}

        💽 *Disk* — {free_gb:.1f} GB free / {total_gb:.1f} GB · CPU {s.get('cpuPercent', 0):.0f}%
    """).strip()


def _fmt_autorun(st: dict) -> str:
    icons = {"pending": "⏳", "running": "🔄", "done": "✅", "error": "❌", "cancelled": "🚫"}
    lines = [f"*AUTO RUN — {st.get('status', 'idle').upper()}*\n"]
    for stage in st.get("stages", []):
        icon = icons.get(stage.get("status", "pending"), "⏳")
        prog = f"  {stage.get('progress', 0)}%" if stage.get("status") != "pending" else ""
        lines.append(f"{icon} {stage.get('name', '?')}{prog}")
    return "\n".join(lines)


def _fmt_progress(items: list) -> str:
    if not items:
        return "📭 No active downloads."
    lines = ["📥 *Active Downloads*\n"]
    for p in items[:12]:
        pct = int(p.get("percent", 0))
        filled = pct // 10
        bar = "█" * filled + "░" * (10 - filled)
        stats = f"{p.get('running', 0)}↓  {p.get('queued', 0)}Q  {p.get('failed', 0)}✗"
        lines.append(f"*{p.get('manga_title', '?')}*\n`{bar}` {pct}%  {stats}")
    if len(items) > 12:
        lines.append(f"_…and {len(items) - 12} more_")
    return "\n\n".join(lines)


# ── Command handlers ──────────────────────────────────────────────────────────

@_guard
async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(dedent(r"""
        👋 *Manga Manager Bot*

        Type naturally or use commands:

        *Overview*
        /status · /progress · /logs

        *AUTO RUN* \(full 5\-stage pipeline\)
        /autorun · /autorun\_stop · /autorun\_status

        *System*
        /flush · /organize · /reindex

        *Downloads*
        /enqueue\_missing · /retry\_failed
        /pause\_queue · /resume\_queue

        *Komga*
        /komga\_scan · /import\_all

        *Scans*
        /full\_scan · /stop\_scan · /stop\_all

        *Library*
        /reorganize · /deduplicate

        *Metadata*
        /discover · /sync

        *Other*
        /reset\_missing · /clear \(clears AI chat history\)

        💬 Or just talk to me\!
    """).strip(), parse_mode="MarkdownV2")


@_guard
async def cmd_status(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        s = await _client.summary()
        await update.message.reply_text(_fmt_summary(s), parse_mode="Markdown")
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_progress(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        items = await _client.progress()
        await update.message.reply_text(_fmt_progress(items), parse_mode="Markdown")
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_logs(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        entries = await _client.logs(20)
        if not entries:
            await update.message.reply_text("📭 No logs.")
            return
        icons = {"info": "ℹ️", "warn": "⚠️", "warning": "⚠️", "error": "❌"}
        lines = ["📋 *Recent Logs*\n"]
        for e in entries[-15:]:
            icon = icons.get((e.get("level") or "").lower(), "•")
            lines.append(f"{icon} {(e.get('message') or '')[:120]}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_autorun(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await _client.auto_run_start()
        await update.message.reply_text(
            "🚀 *AUTO RUN started!*\n\n"
            "1. System Flush\n2. Scan Local Duplicates\n3. Full Library Organize\n"
            "4. Discover Unmatched\n5. Sync Metadata\n\n"
            "Use /autorun\\_status to track progress.",
            parse_mode="Markdown",
        )
    except Exception as exc:
        msg = str(exc)
        if "409" in msg or "already" in msg.lower():
            await update.message.reply_text("⚠️ AUTO RUN is already running. Use /autorun\\_status.", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_autorun_stop(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await _client.auto_run_stop()
        await update.message.reply_text("🛑 AUTO RUN stop requested.")
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_autorun_status(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        st = await _client.auto_run_status()
        await update.message.reply_text(_fmt_autorun(st), parse_mode="Markdown")
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_flush(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await _client.flush_start()
        await update.message.reply_text("⚡ System Flush started.")
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_flush_stop(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await _client.flush_stop()
        await update.message.reply_text("🛑 Flush stop requested.")
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_organize(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await _client.organize_start()
        await update.message.reply_text("📁 Full Library Organize started.")
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_organize_stop(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await _client.organize_stop()
        await update.message.reply_text("🛑 Organize stop requested.")
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_reindex(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        r = await _client.reindex()
        await update.message.reply_text(
            f"📂 Reindex complete — {r.get('books', '?')} books, {r.get('chapters', '?')} chapters."
        )
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_full_scan(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await _client.full_scan()
        await update.message.reply_text("🔍 Full Asura catalog scan started.")
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_stop_scan(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await _client.scan_stop()
        await update.message.reply_text("🛑 Scan stop requested.")
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_stop_all(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await _client.scan_stop_all()
        await update.message.reply_text("🛑 All scans stop requested.")
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_enqueue_missing(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        r = await _client.enqueue_missing()
        await update.message.reply_text(f"📥 Enqueued {r.get('enqueued', '?')} missing chapters.")
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_reset_missing(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        r = await _client.reset_missing()
        await update.message.reply_text(
            f"🔄 Reset missing — manga: {r.get('mangaReset', '?')}, chapters: {r.get('chaptersReset', '?')}."
        )
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_retry_failed(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        r = await _client.retry_failed()
        await update.message.reply_text(f"🔁 Requeued {r.get('requeued', '?')} failed downloads.")
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_pause_queue(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await _client.pause_queue()
        await update.message.reply_text("⏸ Download queue paused.")
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_resume_queue(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await _client.resume_queue()
        await update.message.reply_text("▶️ Download queue resumed.")
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_komga_scan(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await _client.komga_scan_all()
        await update.message.reply_text("🔍 Komga quick scan started.")
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_import_all(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await _client.import_all()
        await update.message.reply_text("📚 Komga import all started.")
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_discover(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        r = await _client.metadata_discover()
        await update.message.reply_text(
            f"🔍 Discover done — processed: {r.get('processed', '?')}, "
            f"auto-linked: {r.get('autoLinked', '?')}, review needed: {r.get('reviewNeeded', '?')}."
        )
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_sync(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        r = await _client.metadata_sync()
        await update.message.reply_text(
            f"🔄 Sync done — synced: {r.get('synced', '?')}, errors: {len(r.get('errors', []))}."
        )
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_reorganize(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await _client.reorganize()
        await update.message.reply_text("📂 Library reorganize started.")
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_deduplicate(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await _client.deduplicate()
        await update.message.reply_text("🗃 Deduplication started.")
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


@_guard
async def cmd_clear(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    _histories.pop(update.effective_user.id, None)
    await update.message.reply_text("🗑 Chat history cleared.")


# ── Natural-language message handler ─────────────────────────────────────────

_INTENT_DISPATCH = {
    "auto_run":        cmd_autorun,
    "auto_run_stop":   cmd_autorun_stop,
    "auto_run_status": cmd_autorun_status,
    "flush":           cmd_flush,
    "flush_stop":      cmd_flush_stop,
    "organize":        cmd_organize,
    "organize_stop":   cmd_organize_stop,
    "reindex":         cmd_reindex,
    "full_scan":       cmd_full_scan,
    "scan_stop":       cmd_stop_scan,
    "scan_stop_all":   cmd_stop_all,
    "enqueue_missing": cmd_enqueue_missing,
    "reset_missing":   cmd_reset_missing,
    "retry_failed":    cmd_retry_failed,
    "pause_queue":     cmd_pause_queue,
    "resume_queue":    cmd_resume_queue,
    "komga_scan":      cmd_komga_scan,
    "import_all":      cmd_import_all,
    "reorganize":      cmd_reorganize,
    "deduplicate":     cmd_deduplicate,
    "discover":        cmd_discover,
    "sync":            cmd_sync,
    "status":          cmd_status,
    "progress":        cmd_progress,
    "logs":            cmd_logs,
}


@_guard
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    uid = update.effective_user.id

    # 1. Try keyword intent matching — fast and reliable
    intent = match_intent(text)
    if intent and intent in _INTENT_DISPATCH:
        log.info("Intent matched: %s for %r", intent, text)
        await _INTENT_DISPATCH[intent](update, ctx)
        return

    # 2. Fall through to AI chat
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    try:
        history = _history(uid)
        reply = await ollama_chat(text, history)
        _record(uid, "user", text)
        _record(uid, "assistant", reply)
        await update.message.reply_text(reply)
    except Exception as exc:
        log.exception("Ollama chat error: %s", exc)
        await update.message.reply_text(
            f"❌ AI error: {exc}\n\nMake sure Ollama is running at the configured URL."
        )


# ── Entry point ───────────────────────────────────────────────────────────────

_COMMANDS = [
    BotCommand("status",          "Library & queue overview"),
    BotCommand("progress",        "Active downloads"),
    BotCommand("logs",            "Recent log entries"),
    BotCommand("autorun",         "Start full AUTO RUN pipeline"),
    BotCommand("autorun_status",  "AUTO RUN stage progress"),
    BotCommand("autorun_stop",    "Stop AUTO RUN"),
    BotCommand("flush",           "Start system flush"),
    BotCommand("flush_stop",      "Stop system flush"),
    BotCommand("organize",        "Full library organize"),
    BotCommand("organize_stop",   "Stop library organize"),
    BotCommand("reindex",         "Reindex local library"),
    BotCommand("full_scan",       "Full Asura catalog scan"),
    BotCommand("stop_scan",       "Stop current scan"),
    BotCommand("stop_all",        "Stop all scans"),
    BotCommand("enqueue_missing", "Queue missing chapters for download"),
    BotCommand("retry_failed",    "Re-queue failed downloads"),
    BotCommand("reset_missing",   "Reset missing chapter flags"),
    BotCommand("pause_queue",     "Pause download queue"),
    BotCommand("resume_queue",    "Resume download queue"),
    BotCommand("komga_scan",      "Trigger Komga quick scan"),
    BotCommand("import_all",      "Trigger Komga import all"),
    BotCommand("reorganize",      "Reorganize library folders"),
    BotCommand("deduplicate",     "Run deduplication"),
    BotCommand("discover",        "Discover unmatched metadata"),
    BotCommand("sync",            "Sync metadata to Komga"),
    BotCommand("clear",           "Clear AI chat history"),
    BotCommand("help",            "Show all commands"),
]


async def _post_init(app: Application) -> None:
    await app.bot.set_my_commands(_COMMANDS)
    log.info("Bot commands registered (%d commands)", len(_COMMANDS))


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).post_init(_post_init).build()

    for name, handler in [
        ("start", cmd_start), ("help", cmd_start),
        ("status", cmd_status), ("progress", cmd_progress), ("logs", cmd_logs),
        ("autorun", cmd_autorun), ("autorun_stop", cmd_autorun_stop), ("autorun_status", cmd_autorun_status),
        ("flush", cmd_flush), ("flush_stop", cmd_flush_stop),
        ("organize", cmd_organize), ("organize_stop", cmd_organize_stop),
        ("reindex", cmd_reindex), ("full_scan", cmd_full_scan),
        ("stop_scan", cmd_stop_scan), ("stop_all", cmd_stop_all),
        ("enqueue_missing", cmd_enqueue_missing), ("reset_missing", cmd_reset_missing),
        ("retry_failed", cmd_retry_failed),
        ("pause_queue", cmd_pause_queue), ("resume_queue", cmd_resume_queue),
        ("komga_scan", cmd_komga_scan), ("import_all", cmd_import_all),
        ("reorganize", cmd_reorganize), ("deduplicate", cmd_deduplicate),
        ("discover", cmd_discover), ("sync", cmd_sync),
        ("clear", cmd_clear),
    ]:
        app.add_handler(CommandHandler(name, handler))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Bot polling. Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

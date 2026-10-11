import os
import io
import html
import logging
import tempfile
from typing import List
from pathlib import Path

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    constants,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from src.config import config
from src.services import (
    parse_resume,
    parse_job_description,
    evaluate_ats_fit,
    generate_resume_improvements,
    recommend_learning_paths,
    generate_markdown_report,
    rank_resumes,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def send_smart_chunks(
    update: Update,
    text: str,
    max_len: int = config.MAX_MESSAGE_LENGTH
):
    """Safely delivers long formatted reports across multiple Telegram messages."""
    if len(text) <= max_len:
        await update.message.reply_text(text, parse_mode=constants.ParseMode.HTML)
        return

    sections = text.split("\n\n")
    current_chunk = ""

    for section in sections:
        if len(current_chunk) + len(section) + 2 > max_len:
            if current_chunk.strip():
                await update.message.reply_text(
                    current_chunk.strip(),
                    parse_mode=constants.ParseMode.HTML
                )
            current_chunk = section + "\n\n"
        else:
            current_chunk += section + "\n\n"

    if current_chunk.strip():
        await update.message.reply_text(
            current_chunk.strip(),
            parse_mode=constants.ParseMode.HTML
        )


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start welcome command."""
    keyboard = [
        [
            InlineKeyboardButton("ℹ️ How it works", callback_data="help"),
            InlineKeyboardButton("🏆 Rank Multiple Resumes", callback_data="rank_info"),
        ],
        [
            InlineKeyboardButton("🔄 Reset Session", callback_data="reset"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_message = (
        "🤖 <b>AI Resume ATS Analyzer & Candidate Ranker</b>\n\n"
        "Maximize your job interview chances or pick the best candidate among multiple resumes!\n\n"
        "<b>How to use:</b>\n"
        "1️⃣ <b>Single Resume:</b>\n"
        "   • Send 1 PDF resume → paste Job Description → get ATS score (0-100), rewrite suggestions, & course roadmap.\n\n"
        "2️⃣ <b>Multi-Resume Ranking (/rank):</b>\n"
        "   • Send 2 or more PDF resumes → paste Job Description → get Candidate Leaderboard & Best Pick!\n\n"
        "<i>Upload your resume PDF to begin, or type /rank to compare multiple candidates.</i>"
    )
    await update.message.reply_text(
        welcome_message,
        reply_markup=reply_markup,
        parse_mode=constants.ParseMode.HTML
    )


async def rank_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enables multi-resume batch ranking mode."""
    context.user_data["batch_mode"] = True
    resumes_list = context.user_data.setdefault("resumes", [])

    count = len(resumes_list)
    msg = (
        "🏆 <b>Batch Candidate Ranking Mode</b>\n\n"
        f"<b>Resumes currently in queue:</b> {count}\n\n"
        "<b>Instructions:</b>\n"
        "1. Send your candidate PDF resumes one after another.\n"
        "2. When all resumes are uploaded, <b>paste the Job Description text</b> to rank all candidates and pick the #1 match!\n\n"
        "<i>Send your PDF resumes now...</i>"
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(msg, parse_mode=constants.ParseMode.HTML)
    else:
        await update.message.reply_text(msg, parse_mode=constants.ParseMode.HTML)


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Provides troubleshooting guidance and instructions."""
    help_message = (
        "📖 <b>ATS Optimization & Ranking Guide</b>\n\n"
        "<b>Single Mode:</b>\n"
        "1. Send a single PDF resume.\n"
        "2. Send target Job Description text.\n"
        "3. Receive ATS score (0-100), missing skills, rewrite suggestions, and downloadable <code>.md</code> report.\n\n"
        "<b>Multi-Resume Ranking Mode:</b>\n"
        "1. Type /rank.\n"
        "2. Send 2 or more PDF resumes.\n"
        "3. Send target Job Description text.\n"
        "4. Receive Candidate Leaderboard with #1 Best Pick!\n\n"
        "<b>Commands:</b>\n"
        "/start - Welcome screen\n"
        "/rank  - Start batch resume ranking\n"
        "/help  - Display this guide\n"
        "/reset - Clear active session"
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(help_message, parse_mode=constants.ParseMode.HTML)
    else:
        await update.message.reply_text(help_message, parse_mode=constants.ParseMode.HTML)


async def reset_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clears the active user session and removes temporary files."""
    for item in context.user_data.get("resumes", []):
        p = item.get("path")
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass

    context.user_data.clear()
    msg = "🔄 <b>Session reset!</b> Upload a new PDF resume or type /rank to start fresh."
    if update.callback_query:
        await update.callback_query.answer("Session cleared!")
        await update.callback_query.message.reply_text(msg, parse_mode=constants.ParseMode.HTML)
    else:
        await update.message.reply_text(msg, parse_mode=constants.ParseMode.HTML)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Catches photo uploads and instructs user to upload as PDF document."""
    await update.message.reply_text(
        "📷 <b>Photo received:</b> The ATS analyzer requires text-selectable documents.\n\n"
        "Please send your resume as a <b>PDF file</b> (choose <i>'Send as File / Document'</i> instead of photo).",
        parse_mode=constants.ParseMode.HTML
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives and stores candidate PDF resumes."""
    doc = update.message.document
    if not doc:
        return

    file_name = doc.file_name or "Resume.pdf"
    mime = (doc.mime_type or "").lower()

    # Supported document extensions
    supported_exts = (".pdf", ".docx", ".doc", ".txt", ".rtf")
    file_ext = Path(file_name).suffix.lower()
    is_supported = file_ext in supported_exts or any(kw in mime for kw in ["pdf", "word", "document", "text"])

    if not is_supported:
        await update.message.reply_text(
            f"❌ <b>Unsupported format:</b> <code>{html.escape(file_name)}</code>\n\n"
            "Please upload your resume as a <b>PDF</b> (<code>.pdf</code>) or <b>Word document</b> (<code>.docx</code>).",
            parse_mode=constants.ParseMode.HTML
        )
        return

    # Check file size (max 20MB)
    if doc.file_size and doc.file_size > 20 * 1024 * 1024:
        await update.message.reply_text("❌ File size exceeds 20MB limit.")
        return

    # Create secure temporary file preserving original extension
    temp_suffix = file_ext if file_ext in supported_exts else ".pdf"
    with tempfile.NamedTemporaryFile(suffix=temp_suffix, delete=False) as tf:
        temp_path = tf.name

    try:
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(temp_path)

        # Store in user session queue
        resumes_list = context.user_data.setdefault("resumes", [])
        resumes_list.append({"name": file_name, "path": temp_path})
        context.user_data["resume_path"] = temp_path
        context.user_data["resume_name"] = file_name

        count = len(resumes_list)

        # Check if user passed Job Description in caption
        caption = (update.message.caption or "").strip()
        if len(caption) >= 30:
            await update.message.reply_text(
                f"📄 <b>Resume received with Job Description in caption!</b>\nAnalyzing now...",
                parse_mode=constants.ParseMode.HTML
            )
            if count > 1 or context.user_data.get("batch_mode"):
                await process_batch_ranking(update, context, resumes_list, caption)
            else:
                await process_single_evaluation(update, context, temp_path, caption)
            return

        # Regular resume upload response
        if count == 1 and not context.user_data.get("batch_mode"):
            await update.message.reply_text(
                f"📄 <b>Resume received:</b> <code>{html.escape(file_name)}</code>\n\n"
                "<b>Next step:</b>\n"
                "• <b>To analyze this resume:</b> Paste the target Job Description now.\n"
                "• <b>To compare multiple resumes:</b> Send more PDF resumes now (or type /rank)!",
                parse_mode=constants.ParseMode.HTML
            )
        else:
            queue_str = "\n".join([f"  {idx+1}. <code>{html.escape(r['name'])}</code>" for idx, r in enumerate(resumes_list)])
            await update.message.reply_text(
                f"✅ <b>Resume #{count} added:</b> <code>{html.escape(file_name)}</code>\n\n"
                f"📋 <b>Resumes in queue ({count}):</b>\n{queue_str}\n\n"
                "<b>Next step:</b>\n"
                "• Send another PDF resume to add to this batch, or\n"
                "• <b>Paste the Job Description</b> now to rank all candidates!",
                parse_mode=constants.ParseMode.HTML
            )
    except Exception as exc:
        logger.error("Failed to download PDF resume: %s", exc, exc_info=True)
        if os.path.exists(temp_path):
            os.remove(temp_path)
        await update.message.reply_text(
            f"❌ <b>Download Error:</b> Could not process <code>{html.escape(file_name)}</code>. Please try uploading again.",
            parse_mode=constants.ParseMode.HTML
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes job description text and computes ATS scoring or batch ranking."""
    resumes_list = context.user_data.get("resumes", [])

    if not resumes_list:
        await update.message.reply_text(
            "⚠️ <b>No resume uploaded!</b>\n\n"
            "Please send your resume as a <b>PDF file</b> first before pasting the job description.",
            parse_mode=constants.ParseMode.HTML
        )
        return

    jd_text = (update.message.text or "").strip()
    if len(jd_text) < 30:
        await update.message.reply_text(
            "⚠️ <b>Job description too brief!</b> Please provide the complete job posting (responsibilities, requirements, qualifications).",
            parse_mode=constants.ParseMode.HTML
        )
        return

    # Decide whether Single Evaluation or Batch Ranking
    if len(resumes_list) > 1 or context.user_data.get("batch_mode"):
        await process_batch_ranking(update, context, resumes_list, jd_text)
    else:
        resume_path = resumes_list[0]["path"]
        await process_single_evaluation(update, context, resume_path, jd_text)


async def process_batch_ranking(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    resumes_list: list,
    jd_text: str
):
    """Evaluates multiple resumes and outputs leaderboard with best pick."""
    paths = [r["path"] for r in resumes_list if os.path.exists(r["path"])]
    if len(paths) == 0:
        await update.message.reply_text("❌ No valid resume files found in session. Please re-upload your PDFs.")
        return

    progress_msg = await update.message.reply_text(
        f"⏳ <b>Ranking {len(paths)} Candidates with Gemini AI...</b>\n"
        "• Parsing candidate qualifications...\n"
        "• Matching against job requirements...\n"
        "• Selecting the #1 Best Match...",
        parse_mode=constants.ParseMode.HTML
    )

    try:
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        ranking = rank_resumes(paths, jd_text)
        top = ranking["top_pick"]
        leaderboard = ranking["leaderboard"]

        try:
            await progress_msg.delete()
        except Exception:
            pass

        role_escaped = html.escape(str(ranking.get('target_role', 'Target Role')))
        top_name_escaped = html.escape(str(top['candidate_name']))
        top_file_escaped = html.escape(str(top['filename']))
        top_status_escaped = html.escape(str(top['status']))

        # Build clean formatted leaderboard
        report = (
            f"🏆 <b>CANDIDATE RANKING LEADERBOARD</b>\n"
            f"<b>Role:</b> {role_escaped}\n"
            f"<b>Candidates Evaluated:</b> {ranking['total_evaluated']}\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🥇 <b>#1 BEST RESUME MATCH:</b> <b>{top_name_escaped.upper()}</b>\n"
            f"• <b>Score:</b> <b>{top['score']}/100</b> ({top_status_escaped})\n"
            f"• <b>File:</b> <code>{top_file_escaped}</code>\n"
            f"• <b>Mandatory Skills Matched:</b> {len(top['matched_required'])}\n\n"
            "📊 <b>LEADERBOARD:</b>\n"
        )

        for c in leaderboard:
            rank_icon = "🥇" if c['rank'] == 1 else ("🥈" if c['rank'] == 2 else ("🥉" if c['rank'] == 3 else f"#{c['rank']}"))
            c_name = html.escape(str(c['candidate_name']))
            c_file = html.escape(str(c['filename']))
            c_status = html.escape(str(c['status']))
            report += (
                f"{rank_icon} <b>{c_name}</b> — <b>{c['score']}/100</b>\n"
                f"   Doc: <code>{c_file}</code> | {c_status}\n"
            )

        await send_smart_chunks(update, report)

        # Deliver downloadable full ranking report document
        report_bytes = io.BytesIO(ranking["report_markdown"].encode("utf-8"))
        report_bytes.name = "Candidate_Ranking_Report.md"
        await update.message.reply_document(
            document=report_bytes,
            filename="Candidate_Ranking_Report.md",
            caption="📥 <b>Download Complete Candidate Ranking Report (.md)</b>",
            parse_mode=constants.ParseMode.HTML
        )

        # Clean up temporary files on success
        for r in resumes_list:
            if os.path.exists(r.get("path", "")):
                try:
                    os.remove(r["path"])
                except Exception:
                    pass
        context.user_data.clear()

    except Exception as exc:
        logger.error("Batch ranking failed: %s", exc, exc_info=True)
        try:
            await progress_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(
            f"❌ <b>Ranking Failed:</b> {html.escape(str(exc))}\n\nPlease check your inputs and try again.",
            parse_mode=constants.ParseMode.HTML
        )


async def process_single_evaluation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    resume_path: str,
    jd_text: str
):
    """Processes single resume evaluation."""
    progress_msg = await update.message.reply_text(
        "⏳ <b>Analyzing Resume Match with Gemini AI...</b>\n"
        "• Parsing resume entities...\n"
        "• Evaluating job requirements...\n"
        "• Running ATS scoring engine...",
        parse_mode=constants.ParseMode.HTML
    )

    try:
        await update.message.reply_chat_action(constants.ChatAction.TYPING)

        # 1. Parse Resume
        resume_text, resume_data = parse_resume(resume_path)

        # 2. Parse Job Description
        jd_data = parse_job_description(jd_text)

        # 3. Calculate ATS Score
        ats_result = evaluate_ats_fit(resume_data, jd_data, resume_text)

        # 4. Generate Targeted Improvements
        improvements = generate_resume_improvements(resume_data, jd_data, ats_result)

        # 5. Recommend Learning Paths
        courses = recommend_learning_paths(
            missing_required=ats_result.get("missing_required", []),
            missing_preferred=ats_result.get("missing_preferred", []),
            job_title=jd_data.get("job_title", "Target Role")
        )

        try:
            await progress_msg.delete()
        except Exception:
            pass

        score = ats_result["overall_score"]
        score_emoji = "🟢" if score >= 80 else ("🟡" if score >= 60 else "🔴")
        bd = ats_result["breakdown"]

        role_name = html.escape(str(jd_data.get('job_title', 'Target Role')))
        report = (
            f"🎯 <b>ATS MATCH REPORT: {score}/100</b> {score_emoji}\n"
            f"<b>Role:</b> {role_name}\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📊 <b>SCORE BREAKDOWN:</b>\n"
            f"• Required Skills: <b>{bd['required_skills']['score']}/{bd['required_skills']['max']}</b>\n"
            f"• Preferred Skills: <b>{bd['preferred_skills']['score']}/{bd['preferred_skills']['max']}</b>\n"
            f"• Experience Match: <b>{bd['experience']['score']}/{bd['experience']['max']}</b> (Detected ~{bd['experience']['detected_years']} yrs)\n"
            f"• Education Match: <b>{bd['education']['score']}/{bd['education']['max']}</b>\n"
            f"• Resume Structure: <b>{bd['structure']['score']}/{bd['structure']['max']}</b>\n"
            f"• Keywords Coverage: <b>{bd['keywords']['score']}/{bd['keywords']['max']}</b>\n\n"
        )

        # Skill Gaps
        report += "🔍 <b>SKILL GAP ANALYSIS:</b>\n"
        if ats_result["missing_required"]:
            report += "🔴 <b>Missing Required Skills:</b>\n"
            for s in ats_result["missing_required"]:
                report += f"  • {html.escape(s.title())}\n"
        else:
            report += "🔴 <b>Missing Required Skills:</b> None! Perfect match 🎉\n"

        if ats_result["missing_preferred"]:
            report += "\n🟡 <b>Missing Preferred Skills:</b>\n"
            for s in ats_result["missing_preferred"]:
                report += f"  • {html.escape(s.title())}\n"
        else:
            report += "\n🟡 <b>Missing Preferred Skills:</b> None! All covered 🎉\n"

        # Actionable Improvements
        crit = improvements.get("critical_improvements", [])
        if crit:
            report += "\n💡 <b>HIGH-IMPACT RESUME ENHANCEMENTS:</b>\n"
            for idx, item in enumerate(crit[:3], 1):
                sec_escaped = html.escape(str(item.get('section', 'General')))
                sug_escaped = html.escape(str(item.get('suggestion', '')))
                ex_escaped = html.escape(str(item.get('example_transformation', '')))
                report += (
                    f"<b>{idx}. {sec_escaped}:</b> {sug_escaped}\n"
                    f"<i>Example:</i> {ex_escaped}\n\n"
                )

        # Recommended Courses
        if courses:
            report += "📚 <b>RECOMMENDED LEARNING PATHS:</b>\n"
            for c in courses[:4]:
                c_title = html.escape(str(c.get('course', '')))
                c_skill = html.escape(str(c.get('skill', '')).title())
                c_plat = html.escape(str(c.get('platform', '')))
                url_part = f" (<a href='{c['url']}'>Link</a>)" if c.get("url") else ""
                report += (
                    f"• <b>{c_title}</b>\n"
                    f"  Skill: <i>{c_skill}</i> | Platform: {c_plat}{url_part}\n"
                )

        await send_smart_chunks(update, report)

        # Send downloadable Markdown report
        try:
            resume_name = context.user_data.get("resume_name", "Resume.pdf")
            md_report = generate_markdown_report(
                resume_name=resume_name,
                jd_title=jd_data.get("job_title", "Target Role"),
                ats_result=ats_result,
                improvements=improvements,
                courses=courses,
            )
            report_bytes = io.BytesIO(md_report.encode("utf-8"))
            report_bytes.name = "ATS_Compatibility_Report.md"
            await update.message.reply_document(
                document=report_bytes,
                filename="ATS_Compatibility_Report.md",
                caption="📥 <b>Download your full ATS Compatibility Report (.md)</b>",
                parse_mode=constants.ParseMode.HTML
            )
        except Exception as doc_exc:
            logger.warning("Could not send report document: %s", doc_exc)

        # Clean up temporary files on success
        if os.path.exists(resume_path):
            try:
                os.remove(resume_path)
            except Exception:
                pass
        context.user_data.clear()

    except Exception as exc:
        logger.error("Single evaluation failed: %s", exc, exc_info=True)
        try:
            await progress_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(
            f"❌ <b>Analysis Failed:</b> {html.escape(str(exc))}\n\nPlease check your inputs and retry.",
            parse_mode=constants.ParseMode.HTML
        )


def create_bot_app() -> Application:
    """Builds and registers handlers on the Telegram Application instance."""
    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is missing! Set it in your .env file.")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("reset", reset_handler))
    app.add_handler(CommandHandler("rank", rank_command_handler))

    app.add_handler(CallbackQueryHandler(help_handler, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(reset_handler, pattern="^reset$"))
    app.add_handler(CallbackQueryHandler(rank_command_handler, pattern="^rank_info$"))

    # Accept all documents and validate PDF extension / mime-type safely
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    return app


def main():
    """Starts the Telegram bot polling loop."""
    print("=" * 60)
    print("🤖 Launching AI Resume ATS Analyzer & Candidate Ranker...")
    print("=" * 60)
    app = create_bot_app()
    print("✓ Handlers registered. Listening for incoming messages...")
    app.run_polling()


if __name__ == "__main__":
    main()

import os
import io
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
        "<b>Modes Available:</b>\n"
        "1️⃣ <b>Single Resume Evaluation:</b>\n"
        "   • Send 1 PDF resume → send Job Description → get ATS score, feedback, & course roadmap.\n\n"
        "2️⃣ <b>Multi-Resume Ranking (/rank):</b>\n"
        "   • Send multiple PDF resumes → send Job Description → get Candidate Leaderboard & Best Pick!\n\n"
        "<i>Upload a PDF resume to begin, or type /rank for batch ranking.</i>"
    )
    await update.message.reply_text(
        welcome_message,
        reply_markup=reply_markup,
        parse_mode=constants.ParseMode.HTML
    )


async def rank_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enables multi-resume batch ranking mode."""
    context.user_data["batch_mode"] = True
    context.user_data.setdefault("resumes", [])

    count = len(context.user_data["resumes"])
    msg = (
        "🏆 <b>Batch Candidate Ranking Mode Activated!</b>\n\n"
        f"<b>Resumes currently uploaded:</b> {count}\n\n"
        "<b>Instructions:</b>\n"
        "1. Send your candidate PDF resumes one by one.\n"
        "2. When all resumes are uploaded, <b>paste the Job Description text</b> to evaluate and pick the best match!\n\n"
        "<i>Send your first PDF resume now...</i>"
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
        "3. Receive ATS score (0-100), missing skills, rewrite suggestions, and downloadable `.md` report.\n\n"
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
    # Clean single resume
    single = context.user_data.get("resume_path")
    if single and os.path.exists(single):
        try:
            os.remove(single)
        except Exception:
            pass

    # Clean batch resumes
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


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives and stores candidate PDF resumes."""
    doc = update.message.document

    if not doc.file_name or not doc.file_name.lower().endswith(".pdf"):
        await update.message.reply_text(
            "❌ <b>Unsupported format!</b> Please send your resume as a <b>PDF</b> document.",
            parse_mode=constants.ParseMode.HTML
        )
        return

    # Check file size (max 15MB)
    if doc.file_size and doc.file_size > 15 * 1024 * 1024:
        await update.message.reply_text("❌ PDF file size exceeds 15MB limit.")
        return

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        temp_path = tf.name

    try:
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(temp_path)

        # Batch mode or multiple resumes uploaded
        resumes_list = context.user_data.setdefault("resumes", [])
        resumes_list.append({"name": doc.file_name, "path": temp_path})
        context.user_data["resume_path"] = temp_path
        context.user_data["resume_name"] = doc.file_name

        count = len(resumes_list)
        if count == 1 and not context.user_data.get("batch_mode"):
            await update.message.reply_text(
                f"📄 <b>Resume received:</b> <code>{doc.file_name}</code>\n\n"
                "• <b>To analyze this resume:</b> Paste the target Job Description now.\n"
                "• <b>To compare multiple resumes:</b> Send more PDFs or type /rank!",
                parse_mode=constants.ParseMode.HTML
            )
        else:
            await update.message.reply_text(
                f"✅ <b>Resume #{count} added:</b> <code>{doc.file_name}</code>\n\n"
                f"Total resumes queued: <b>{count}</b>\n"
                "• Send another PDF resume, or\n"
                "• <b>Paste the Job Description</b> now to rank all candidates!",
                parse_mode=constants.ParseMode.HTML
            )
    except Exception as exc:
        logger.error("Failed to download PDF resume: %s", exc, exc_info=True)
        if os.path.exists(temp_path):
            os.remove(temp_path)
        await update.message.reply_text(
            "❌ <b>Download Error:</b> Could not process your PDF. Please try uploading it again.",
            parse_mode=constants.ParseMode.HTML
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes job description text and computes ATS scoring or batch ranking."""
    resumes_list = context.user_data.get("resumes", [])

    if not resumes_list and not context.user_data.get("resume_path"):
        await update.message.reply_text(
            "⚠️ <b>Missing Resume!</b> Please send at least one PDF resume before sending the job description.",
            parse_mode=constants.ParseMode.HTML
        )
        return

    jd_text = (update.message.text or "").strip()
    if len(jd_text) < 30:
        await update.message.reply_text(
            "⚠️ <b>Job description too brief!</b> Please provide the complete job posting.",
            parse_mode=constants.ParseMode.HTML
        )
        return

    # Decide whether Single Evaluation or Batch Ranking
    if len(resumes_list) > 1 or context.user_data.get("batch_mode"):
        await process_batch_ranking(update, context, resumes_list, jd_text)
    else:
        resume_path = context.user_data["resume_path"]
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
        await update.message.reply_text("❌ No valid resume files found. Please re-upload your PDFs.")
        return

    progress_msg = await update.message.reply_text(
        f"⏳ <b>Ranking {len(paths)} Candidates with Gemini AI...</b>\n"
        "• Parsing all candidate entities...\n"
        "• Benchmarking against job requirements...\n"
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

        # Build clean formatted leaderboard
        report = (
            f"🏆 <b>CANDIDATE RANKING LEADERBOARD</b>\n"
            f"<b>Role:</b> {ranking['target_role']}\n"
            f"<b>Candidates Evaluated:</b> {ranking['total_evaluated']}\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🥇 <b>#1 BEST RESUME MATCH:</b> <b>{top['candidate_name'].upper()}</b>\n"
            f"• <b>Score:</b> <b>{top['score']}/100</b> ({top['status']})\n"
            f"• <b>File:</b> <code>{top['filename']}</code>\n"
            f"• <b>Mandatory Skills Matched:</b> {len(top['matched_required'])}\n\n"
            "📊 <b>LEADERBOARD:</b>\n"
        )

        for c in leaderboard:
            rank_icon = "🥇" if c['rank'] == 1 else ("🥈" if c['rank'] == 2 else ("🥉" if c['rank'] == 3 else f"#{c['rank']}"))
            report += (
                f"{rank_icon} <b>{c['candidate_name']}</b> — <b>{c['score']}/100</b>\n"
                f"   Doc: <code>{c['filename']}</code> | {c['status']}\n"
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

    except Exception as exc:
        logger.error("Batch ranking failed: %s", exc, exc_info=True)
        await update.message.reply_text(
            f"❌ <b>Ranking Failed:</b> {str(exc)}\nPlease check your inputs and try again.",
            parse_mode=constants.ParseMode.HTML
        )
    finally:
        # Cleanup
        for r in resumes_list:
            if os.path.exists(r.get("path", "")):
                try:
                    os.remove(r["path"])
                except Exception:
                    pass
        context.user_data.clear()


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

        report = (
            f"🎯 <b>ATS MATCH REPORT: {score}/100</b> {score_emoji}\n"
            f"<b>Role:</b> {jd_data.get('job_title', 'Target Role')}\n"
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
                report += f"  • {s.title()}\n"
        else:
            report += "🔴 <b>Missing Required Skills:</b> None! Perfect match 🎉\n"

        if ats_result["missing_preferred"]:
            report += "\n🟡 <b>Missing Preferred Skills:</b>\n"
            for s in ats_result["missing_preferred"]:
                report += f"  • {s.title()}\n"
        else:
            report += "\n🟡 <b>Missing Preferred Skills:</b> None! All covered 🎉\n"

        # Actionable Improvements
        crit = improvements.get("critical_improvements", [])
        if crit:
            report += "\n💡 <b>HIGH-IMPACT RESUME ENHANCEMENTS:</b>\n"
            for idx, item in enumerate(crit[:3], 1):
                report += (
                    f"<b>{idx}. {item.get('section', 'General')}:</b> {item.get('suggestion')}\n"
                    f"<i>Example:</i> {item.get('example_transformation')}\n\n"
                )

        # Recommended Courses
        if courses:
            report += "📚 <b>RECOMMENDED LEARNING PATHS:</b>\n"
            for c in courses[:4]:
                url_part = f" (<a href='{c['url']}'>Link</a>)" if c.get("url") else ""
                report += (
                    f"• <b>{c.get('course')}</b>\n"
                    f"  Skill: <i>{c.get('skill', '').title()}</i> | Platform: {c.get('platform')}{url_part}\n"
                )

        await send_smart_chunks(update, report)

        # Send downloadable Markdown report
        try:
            md_report = generate_markdown_report(
                resume_name=context.user_data.get("resume_name", "Resume.pdf"),
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

    except Exception as exc:
        logger.error("Single evaluation failed: %s", exc, exc_info=True)
        await update.message.reply_text(
            f"❌ <b>Analysis Failed:</b> {str(exc)}\nPlease check your inputs and retry.",
            parse_mode=constants.ParseMode.HTML
        )
    finally:
        if os.path.exists(resume_path):
            try:
                os.remove(resume_path)
            except Exception:
                pass
        context.user_data.clear()


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

    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
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

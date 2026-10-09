import os
import logging
import tempfile
from typing import List

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

    # Split logically across headers
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
            InlineKeyboardButton("🔄 Reset Session", callback_data="reset"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_message = (
        "🤖 <b>AI Resume ATS Analyzer</b>\n\n"
        "Maximize your job interview chances with instant, AI-driven ATS compatibility scoring!\n\n"
        "<b>Workflow:</b>\n"
        "1️⃣ <b>Send your Resume</b> as a PDF file.\n"
        "2️⃣ <b>Paste the Job Description (JD)</b> as plain text.\n\n"
        "<b>What you will receive:</b>\n"
        "• 🎯 Overall Match Score (0–100%)\n"
        "• 📊 Category-by-category Breakdown (Skills, Experience, Education, Keywords)\n"
        "• 🔍 Missing Required & Preferred Skills\n"
        "• 💡 Actionable Bullet Point Transformations\n"
        "• 📚 Targeted Course Recommendations & Roadmaps\n\n"
        "<i>Upload your resume PDF to begin!</i>"
    )
    await update.message.reply_text(
        welcome_message,
        reply_markup=reply_markup,
        parse_mode=constants.ParseMode.HTML
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Provides troubleshooting guidance and instructions."""
    help_message = (
        "📖 <b>ATS Optimization Guide</b>\n\n"
        "<b>Tips for higher scores:</b>\n"
        "• Ensure your PDF is text-searchable (not an image scan or flattened canvas).\n"
        "• Include standard headings: <i>Skills, Experience, Education, Projects, Certifications</i>.\n"
        "• Paste the full job description text including requirements and nice-to-haves.\n"
        "• Quantify your achievements with metrics (e.g., %, $, throughput, speed).\n\n"
        "<b>Available Commands:</b>\n"
        "/start - Launch the bot\n"
        "/help  - Display this guide\n"
        "/reset - Clear active session"
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            help_message,
            parse_mode=constants.ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            help_message,
            parse_mode=constants.ParseMode.HTML
        )


async def reset_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clears the active user session and removes temporary files."""
    resume_path = context.user_data.get("resume_path")
    if resume_path and os.path.exists(resume_path):
        try:
            os.remove(resume_path)
        except Exception as exc:
            logger.warning("Error removing temp resume: %s", exc)

    context.user_data.clear()

    msg = "🔄 <b>Session reset!</b> Please upload your PDF resume to start fresh."
    if update.callback_query:
        await update.callback_query.answer("Session cleared!")
        await update.callback_query.message.reply_text(msg, parse_mode=constants.ParseMode.HTML)
    else:
        await update.message.reply_text(msg, parse_mode=constants.ParseMode.HTML)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives and stores the candidate's PDF resume."""
    doc = update.message.document

    if not doc.file_name or not doc.file_name.lower().endswith(".pdf"):
        await update.message.reply_text(
            "❌ <b>Unsupported file format!</b> Please send your resume as a <b>PDF</b> document.",
            parse_mode=constants.ParseMode.HTML
        )
        return

    # Clean previous resume if present
    prev_path = context.user_data.get("resume_path")
    if prev_path and os.path.exists(prev_path):
        try:
            os.remove(prev_path)
        except Exception:
            pass

    # Save to secure temporary file
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        temp_path = tf.name

    try:
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(temp_path)

        context.user_data["resume_path"] = temp_path
        context.user_data["resume_name"] = doc.file_name

        await update.message.reply_text(
            f"📄 <b>Resume received:</b> <code>{doc.file_name}</code>\n\n"
            "Now, <b>paste the job description text</b> for the role you're applying for.",
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
    """Processes job description text and computes the full ATS report."""
    resume_path = context.user_data.get("resume_path")

    if not resume_path or not os.path.exists(resume_path):
        await update.message.reply_text(
            "⚠️ <b>Missing Resume!</b> Please send your resume as a PDF file first before pasting the job description.",
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

    progress_msg = await update.message.reply_text(
        "⏳ <b>Analyzing Match...</b>\n"
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

        # Delete progress message
        try:
            await progress_msg.delete()
        except Exception:
            pass

        # Build clean formatted report
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

        # Send formatted report
        await send_smart_chunks(update, report)

    except Exception as exc:
        logger.error("Analysis pipeline failed: %s", exc, exc_info=True)
        try:
            await progress_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(
            f"❌ <b>Analysis Failed:</b> {str(exc)}\n\nPlease ensure your inputs are clear and retry.",
            parse_mode=constants.ParseMode.HTML
        )
    finally:
        # Cleanup temp file
        if resume_path and os.path.exists(resume_path):
            try:
                os.remove(resume_path)
            except Exception:
                pass
        context.user_data.clear()


def create_bot_app() -> Application:
    """Builds and registers handlers on the Telegram Application instance."""
    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN is missing! Set it in your .env file."
        )

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("reset", reset_handler))

    app.add_handler(CallbackQueryHandler(help_handler, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(reset_handler, pattern="^reset$"))

    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    return app


def main():
    """Starts the Telegram bot polling loop."""
    print("=" * 60)
    print("🤖 Launching AI Resume ATS Analyzer Bot...")
    print("=" * 60)
    app = create_bot_app()
    print("✓ Handlers registered. Listening for incoming messages...")
    app.run_polling()


if __name__ == "__main__":
    main()

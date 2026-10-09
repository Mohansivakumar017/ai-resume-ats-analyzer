import os
import logging
import tempfile
from pathlib import Path
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from resume_analyzer import extract_resume
from jd_analyzer import extract_jd
from ats_scorer import calculate_ats_score
from improvement_generator import generate_improvements
from course_recommender import recommend_courses

# Load environment configuration
load_dotenv()
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# In-memory user state: user_id -> {"resume_path": ...}
user_data = {}


async def send_chunked_message(update: Update, text: str, max_chunk_size: int = 4000):
    """
    Sends message in chunks if it exceeds Telegram's 4096 character limit.
    """
    if len(text) <= max_chunk_size:
        await update.message.reply_text(text)
        return

    # Split into multiple messages cleanly
    lines = text.split("\n")
    current_chunk = ""
    for line in lines:
        if len(current_chunk) + len(line) + 1 > max_chunk_size:
            await update.message.reply_text(current_chunk)
            current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"

    if current_chunk.strip():
        await update.message.reply_text(current_chunk)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    welcome_text = (
        "👋 Welcome to the AI Resume ATS Analyzer Bot!\n\n"
        "How to use:\n"
        "1️⃣ Send your Resume as a PDF file.\n"
        "2️⃣ Send the target Job Description (JD) as plain text.\n\n"
        "What you will get:\n"
        "🎯 Overall ATS Match Score (out of 100)\n"
        "📊 Detailed Score Breakdown (Skills, Experience, Education, Keywords, Structure)\n"
        "🔍 Missing Required & Preferred Skills\n"
        "💡 Tailored Resume Improvement Recommendations\n"
        "📚 Curated Course & Learning Recommendations\n\n"
        "Send your PDF resume to begin, or type /help for more information."
    )
    await update.message.reply_text(welcome_text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /help command."""
    help_text = (
        "ℹ️ ATS Analyzer Bot Help\n\n"
        "Commands:\n"
        "/start - Start or restart the bot\n"
        "/help  - View instructions\n"
        "/reset - Clear current session and start over\n\n"
        "Tips for best results:\n"
        "• Ensure your PDF resume contains selectable text (not an image scan).\n"
        "• Paste the full job description text, including responsibilities and qualifications."
    )
    await update.message.reply_text(help_text)


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clears the user's active session."""
    user_id = update.effective_user.id
    if user_id in user_data:
        path = user_data[user_id].get("resume_path")
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
        del user_data[user_id]
        await update.message.reply_text("🔄 Session cleared! Send a new PDF resume whenever you are ready.")
    else:
        await update.message.reply_text("You don't have an active session. Send a PDF resume to start!")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles incoming PDF resume uploads."""
    document = update.message.document

    if not document.file_name or not document.file_name.lower().endswith(".pdf"):
        await update.message.reply_text("❌ Please send a valid PDF document.")
        return

    # Create safe temporary file
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
        temp_path = temp_file.name

    try:
        telegram_file = await document.get_file()
        await telegram_file.download_to_drive(temp_path)

        # Store in user state
        user_id = update.effective_user.id
        # Clean up old resume if one was already stored
        if user_id in user_data and os.path.exists(user_data[user_id].get("resume_path", "")):
            try:
                os.remove(user_data[user_id]["resume_path"])
            except Exception:
                pass

        user_data[user_id] = {"resume_path": temp_path}

        await update.message.reply_text(
            "✅ Resume received and saved!\n\n"
            "Now, please send or paste the target Job Description (as text)."
        )
    except Exception as exc:
        logger.error("Error downloading PDF: %s", exc, exc_info=True)
        if os.path.exists(temp_path):
            os.remove(temp_path)
        await update.message.reply_text("❌ Failed to process your PDF. Please try uploading again.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles incoming job description text and runs the ATS analysis."""
    user_id = update.effective_user.id

    if user_id not in user_data or "resume_path" not in user_data[user_id]:
        await update.message.reply_text(
            "⚠️ Please upload your resume PDF first!\n"
            "Once uploaded, you can send the job description text."
        )
        return

    jd_text = (update.message.text or "").strip()
    if len(jd_text) < 20:
        await update.message.reply_text("❌ The job description seems too short. Please provide a more detailed job description.")
        return

    resume_path = user_data[user_id]["resume_path"]

    status_message = await update.message.reply_text(
        "🔍 Analyzing your resume and job description with Gemini AI...\n"
        "This may take a few moments ⏳"
    )

    try:
        # Step 1: Extract and analyze resume
        resume_text, resume_data = extract_resume(resume_path)

        # Step 2: Extract job description
        jd_data = extract_jd(jd_text)

        # Step 3: Calculate ATS score
        ats_result = calculate_ats_score(resume_data, jd_data, resume_text)

        # Step 4: Generate improvements
        improvements = generate_improvements(resume_data, jd_data, ats_result)

        # Step 5: Recommend courses
        courses = recommend_courses(
            missing_required=ats_result.get("missing_required", []),
            missing_preferred=ats_result.get("missing_preferred", [])
        )

        # Step 6: Format comprehensive report
        report = (
            "📊 ATS COMPATIBILITY REPORT\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎯 Overall Score: {ats_result['score']}/100\n\n"
            "📋 SCORE BREAKDOWN\n"
            f"• Required Skills: {ats_result['required_skill_score']}/40\n"
            f"• Preferred Skills: {ats_result['preferred_skill_score']}/15\n"
            f"• Experience: {ats_result['experience_score']}/15\n"
            f"• Education: {ats_result['education_score']}/10\n"
            f"• Resume Structure: {ats_result['structure_score']}/10\n"
            f"• Keyword Coverage: {ats_result['keyword_score']}/10\n\n"
            "❌ SKILL GAP ANALYSIS\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🔴 Required Skills Missing:\n"
        )

        if ats_result.get("missing_required"):
            for skill in ats_result["missing_required"]:
                report += f"  • {skill.title()}\n"
        else:
            report += "  • None! You match all required skills 🎉\n"

        report += "\n🟡 Preferred Skills Missing:\n"
        if ats_result.get("missing_preferred"):
            for skill in ats_result["missing_preferred"]:
                report += f"  • {skill.title()}\n"
        else:
            report += "  • None! You match all preferred skills 🎉\n"

        report += (
            "\n💡 RESUME IMPROVEMENT SUGGESTIONS\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
        )
        for item in improvements.get("improvements", []):
            report += f"• {item}\n"

        if courses:
            report += (
                "\n📚 RECOMMENDED COURSES & RESOURCES\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
            )
            for c in courses[:6]:
                url_str = f"\n   🔗 Link: {c['url']}" if c.get("url") else ""
                report += (
                    f"📘 {c['course']}\n"
                    f"   Skill: {c['skill'].title()} | Priority: {c['priority']}\n"
                    f"   Platform: {c['platform']}{url_str}\n\n"
                )

        await send_chunked_message(update, report)

    except Exception as exc:
        logger.error("Analysis failed: %s", exc, exc_info=True)
        await update.message.reply_text(
            f"❌ An error occurred during analysis: {str(exc)}\n\n"
            "Please check that your inputs are clear and try again."
        )

    finally:
        # Cleanup temp file and state
        if os.path.exists(resume_path):
            try:
                os.remove(resume_path)
            except Exception:
                pass
        user_data.pop(user_id, None)


def main():
    if not TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN environment variable is missing. Check your .env file.")
        return

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Resume ATS Bot is running! Press Ctrl+C to stop.")
    application.run_polling()


if __name__ == "__main__":
    main()
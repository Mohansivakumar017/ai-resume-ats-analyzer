import os
import io
import re
import html
import shutil
import logging
import tempfile
from typing import List, Dict, Any, Union
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
    format_progress_bar,
    rank_resumes,
    extract_candidate_name,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def send_smart_chunks(
    update: Update,
    text: str,
    max_len: int = config.MAX_MESSAGE_LENGTH,
    reply_markup: InlineKeyboardMarkup = None,
):
    """Safely delivers long formatted reports across multiple Telegram messages."""
    if len(text) <= max_len:
        await update.message.reply_text(
            text,
            parse_mode=constants.ParseMode.HTML,
            reply_markup=reply_markup,
        )
        return

    sections = text.split("\n\n")
    chunks = []
    current_chunk = ""

    for section in sections:
        if len(current_chunk) + len(section) + 2 > max_len:
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
            current_chunk = section + "\n\n"
        else:
            current_chunk += section + "\n\n"

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    for idx, chunk in enumerate(chunks):
        is_last = (idx == len(chunks) - 1)
        await update.message.reply_text(
            chunk,
            parse_mode=constants.ParseMode.HTML,
            reply_markup=reply_markup if is_last else None,
        )


def cleanup_session_resumes(context: ContextTypes.DEFAULT_TYPE):
    """Safely cleans up temporary resume files and directories from disk."""
    resumes = context.user_data.get("resumes", [])
    for item in resumes:
        p = item.get("path")
        if p and os.path.exists(p):
            try:
                os.remove(p)
                parent = Path(p).parent
                if "ats_resume_" in parent.name and parent.exists():
                    shutil.rmtree(parent, ignore_errors=True)
            except Exception as e:
                logger.debug("Failed cleaning resume %s: %s", p, e)

    legacy_path = context.user_data.get("resume_path")
    if legacy_path and os.path.exists(legacy_path):
        try:
            os.remove(legacy_path)
            parent = Path(legacy_path).parent
            if "ats_resume_" in parent.name and parent.exists():
                shutil.rmtree(parent, ignore_errors=True)
        except Exception:
            pass

    context.user_data["resumes"] = []
    context.user_data.pop("resume_path", None)
    context.user_data.pop("resume_name", None)
    context.user_data.pop("batch_mode", None)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start welcome command."""
    context.user_data.pop("batch_mode", None)
    keyboard = [
        [
            InlineKeyboardButton("📄 Single Evaluation", callback_data="single_mode"),
            InlineKeyboardButton("🏆 Rank Multiple Resumes", callback_data="rank_info"),
        ],
        [
            InlineKeyboardButton("ℹ️ How it works", callback_data="help"),
            InlineKeyboardButton("🔄 Reset Session", callback_data="reset"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_message = (
        "🤖 <b>AI Resume ATS Analyzer & Candidate Ranker</b>\n\n"
        "Maximize your job interview chances or pick the best candidate among multiple resumes!\n\n"
        "<b>Supported Formats:</b> <b>PDF</b> (<code>.pdf</code>), <b>Word</b> (<code>.docx</code>), and <b>Text</b> (<code>.txt</code>).\n\n"
        "<b>Available Modes:</b>\n"
        "1️⃣ <b>Single Resume Evaluation (/single):</b>\n"
        "   • Send 1 resume → paste Job Description → get ATS Score (0-100), 6-dimension breakdown, Before vs. After rewrites, and learning roadmap.\n\n"
        "2️⃣ <b>Multi-Resume Ranking (/rank):</b>\n"
        "   • Send 2 or more candidate resumes → paste Job Description → get Candidate Leaderboard with #1 Best Pick!\n\n"
        "<i>Upload your resume now to begin, or choose an option below.</i>"
    )
    await update.message.reply_text(
        welcome_message,
        reply_markup=reply_markup,
        parse_mode=constants.ParseMode.HTML
    )


async def single_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Switches session explicitly to single resume evaluation mode."""
    context.user_data.pop("batch_mode", None)
    resumes_list = context.user_data.get("resumes", [])
    count = len(resumes_list)
    msg = (
        "📄 <b>Single Resume Evaluation Mode Active</b>\n\n"
        "<b>How it works:</b>\n"
        "1. Send your resume (<b>PDF</b> or <b>DOCX</b>).\n"
        "2. Paste the target Job Description text.\n"
        "3. Receive ATS score (0-100), 6-dimension breakdown, skill gaps, Before vs. After rewrites, and learning courses!\n\n"
    )
    if count == 1:
        msg += f"<i>Current resume in queue:</i> <code>{html.escape(resumes_list[0]['name'])}</code>\nPaste your Job Description now to evaluate!"
    elif count > 1:
        msg += f"<i>Note: You have {count} resumes queued. Type /reset to start fresh or paste Job Description to evaluate.</i>"
    else:
        msg += "<i>Send your PDF or DOCX resume now to begin...</i>"

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(msg, parse_mode=constants.ParseMode.HTML)
    else:
        await update.message.reply_text(msg, parse_mode=constants.ParseMode.HTML)


async def rank_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enables multi-resume batch ranking mode."""
    context.user_data["batch_mode"] = True
    resumes_list = context.user_data.setdefault("resumes", [])

    count = len(resumes_list)
    msg = (
        "🏆 <b>Batch Candidate Ranking Mode Active</b>\n\n"
        f"<b>Resumes currently in queue:</b> {count}\n\n"
        "<b>Instructions:</b>\n"
        "1. Send candidate resumes (<b>PDF</b> or <b>DOCX</b>) one after another.\n"
        "2. When all resumes are uploaded, <b>paste the Job Description text</b> to rank all candidates and pick the #1 match!\n\n"
        "<i>Send candidate resumes now (or type /single to switch to single evaluation)...</i>"
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
        "<b>1. Single Resume Mode (/single):</b>\n"
        "• Send 1 resume (<b>PDF</b> or <b>DOCX</b>).\n"
        "• Paste target Job Description text.\n"
        "• Receive ATS score (0-100), 6-dimension breakdown, skill gaps, Before vs. After rewrites, and downloadable <code>.md</code> report.\n\n"
        "<b>2. Multi-Resume Ranking Mode (/rank):</b>\n"
        "• Type /rank.\n"
        "• Send 2 or more candidate resumes.\n"
        "• Paste target Job Description text.\n"
        "• Receive Candidate Leaderboard with #1 Best Pick, comparative analysis, and recruiter interview tips!\n\n"
        "<b>Commands:</b>\n"
        "/single - Single resume evaluation mode\n"
        "/rank   - Multi-resume candidate ranking mode\n"
        "/start  - Welcome screen\n"
        "/help   - Display this guide\n"
        "/reset  - Clear active session"
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(help_message, parse_mode=constants.ParseMode.HTML)
    else:
        await update.message.reply_text(help_message, parse_mode=constants.ParseMode.HTML)


async def reset_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clears the active user session and removes temporary files."""
    cleanup_session_resumes(context)
    context.user_data.clear()
    msg = (
        "🔄 <b>Session reset!</b>\n\n"
        "Upload a new resume (<b>PDF</b> or <b>DOCX</b>) to analyze, or type /rank to compare multiple resumes."
    )
    if update.callback_query:
        await update.callback_query.answer("Session cleared!")
        await update.callback_query.message.reply_text(msg, parse_mode=constants.ParseMode.HTML)
    else:
        await update.message.reply_text(msg, parse_mode=constants.ParseMode.HTML)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Catches photo uploads and instructs user to upload as document."""
    await update.message.reply_text(
        "📷 <b>Photo received:</b> The ATS analyzer requires text-selectable documents.\n\n"
        "Please send your resume as a <b>PDF</b> or <b>Word DOCX file</b> (choose <i>'Send as File / Document'</i> instead of photo).",
        parse_mode=constants.ParseMode.HTML
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives and stores candidate resumes in PDF, DOCX, or TXT format."""
    doc = update.message.document
    if not doc:
        return

    file_name = doc.file_name or "Resume.pdf"
    mime = (doc.mime_type or "").lower()

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

    if doc.file_size and doc.file_size > 20 * 1024 * 1024:
        await update.message.reply_text("❌ File size exceeds 20MB limit.")
        return

    # Create isolated folder preserving original sanitized filename
    temp_dir = tempfile.mkdtemp(prefix="ats_resume_")
    clean_name = re.sub(r'[^\w\s\.\-]', '_', file_name).strip()
    if not clean_name:
        clean_name = f"Resume{file_ext if file_ext in supported_exts else '.pdf'}"
    temp_path = os.path.join(temp_dir, clean_name)

    try:
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(temp_path)

        # Store in user session queue with original uploaded file name
        resumes_list = context.user_data.setdefault("resumes", [])
        resume_item = {"name": file_name, "path": temp_path}
        resumes_list.append(resume_item)
        context.user_data["resume_path"] = temp_path
        context.user_data["resume_name"] = file_name

        count = len(resumes_list)

        # Check if user passed Job Description in caption
        caption = (update.message.caption or "").strip()
        if len(caption) >= 30:
            await update.message.reply_text(
                f"📄 <b>Resume received:</b> <code>{html.escape(file_name)}</code>\nAnalyzing against Job Description in caption...",
                parse_mode=constants.ParseMode.HTML
            )
            if count > 1:
                await process_batch_ranking(update, context, resumes_list, caption)
            else:
                await process_single_evaluation(update, context, resume_item, caption)
            return

        # Regular resume upload response
        if count == 1 and not context.user_data.get("batch_mode"):
            await update.message.reply_text(
                f"📄 <b>Resume received:</b> <code>{html.escape(file_name)}</code>\n\n"
                "<b>Next step:</b>\n"
                "• <b>To analyze this resume:</b> Paste the target Job Description now.\n"
                "• <b>To compare multiple candidates:</b> Send more resumes now (or type /rank)!",
                parse_mode=constants.ParseMode.HTML
            )
        elif count == 1 and context.user_data.get("batch_mode"):
            await update.message.reply_text(
                f"📄 <b>Resume #1 added:</b> <code>{html.escape(file_name)}</code>\n\n"
                "<b>Next step:</b>\n"
                "• <b>To rank multiple candidates:</b> Send resume #2 now.\n"
                "• <b>To evaluate just this resume:</b> Paste the target Job Description now!",
                parse_mode=constants.ParseMode.HTML
            )
        else:
            queue_str = "\n".join([f"  {idx+1}. <code>{html.escape(r['name'])}</code>" for idx, r in enumerate(resumes_list)])
            await update.message.reply_text(
                f"✅ <b>Resume #{count} added:</b> <code>{html.escape(file_name)}</code>\n\n"
                f"📋 <b>Resumes in queue ({count}):</b>\n{queue_str}\n\n"
                "<b>Next step:</b>\n"
                "• Send another resume (PDF/DOCX) to add to this batch, or\n"
                "• <b>Paste the Job Description</b> now to rank all candidates!",
                parse_mode=constants.ParseMode.HTML
            )
    except Exception as exc:
        logger.error("Failed to download resume %s: %s", file_name, exc, exc_info=True)
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
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
            "Please send your resume as a <b>PDF</b> or <b>DOCX</b> file first before pasting the job description.",
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

    # If 2 or more resumes in queue -> Batch Ranking Leaderboard
    # If 1 resume in queue -> Single Resume ATS Evaluation
    if len(resumes_list) > 1:
        await process_batch_ranking(update, context, resumes_list, jd_text)
    else:
        resume_item = resumes_list[0]
        await process_single_evaluation(update, context, resume_item, jd_text)


async def candidate_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays detailed candidate scorecard when user clicks an inspector button."""
    query = update.callback_query
    await query.answer()

    data = query.data
    try:
        cand_num = int(data.split("_")[1])
    except Exception:
        return

    leaderboard = context.user_data.get("cached_leaderboard", [])
    match = next((c for c in leaderboard if c.get("rank") == cand_num), None)

    if not match:
        await query.message.reply_text("Candidate profile is no longer in active cache. Type /rank to evaluate again.")
        return

    bd = match.get("breakdown", {})
    req_bd = bd.get("required_skills", {})
    pref_bd = bd.get("preferred_skills", {})
    exp_bd = bd.get("experience", {})
    contact = match.get("contact", {})

    contact_parts = []
    if contact.get("email"):
        contact_parts.append(f"📧 {html.escape(contact['email'])}")
    if contact.get("phone"):
        contact_parts.append(f"📱 {html.escape(contact['phone'])}")
    contact_str = " | ".join(contact_parts) if contact_parts else "None detected"

    score = match["score"]
    score_bar = format_progress_bar(score, 100, 10)

    detail_msg = (
        f"🔍 <b>CANDIDATE #{match['rank']} SCORECARD</b>\n"
        f"👤 <b>Name:</b> <b>{html.escape(match['candidate_name'])}</b>\n"
        f"📄 <b>File:</b> <code>{html.escape(match['filename'])}</code>\n"
        f"🎯 <b>ATS Score:</b> <b>{score}/100</b> ({html.escape(match['status'])})\n"
        f"📊 <b>ATS Gauge:</b> <code>[{score_bar}]</code>\n"
        f"💼 <b>Detected Exp:</b> ~{exp_bd.get('detected_years', 0)} years\n"
        f"📞 <b>Contact:</b> {contact_str}\n"
        f"💡 <b>Hiring Verdict:</b> <i>{html.escape(match['recommendation'])}</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📋 <b>Scorecard Breakdown:</b>\n"
        f"• Core Required Skills: <b>{req_bd.get('score', 0)}/{req_bd.get('max', 40)}</b> pts\n"
        f"• Preferred Bonus Skills: <b>{pref_bd.get('score', 0)}/{pref_bd.get('max', 15)}</b> pts\n"
        f"• Experience Match: <b>{exp_bd.get('score', 0)}/{exp_bd.get('max', 20)}</b> pts\n\n"
    )

    all_matched = match.get("matched_required", []) + match.get("matched_preferred", [])
    if all_matched:
        detail_msg += f"✅ <b>Matched Competencies ({len(all_matched)}):</b>\n"
        detail_msg += ", ".join([f"<code>{html.escape(s.title())}</code>" for s in all_matched[:10]]) + "\n\n"

    if match.get("missing_required"):
        detail_msg += "🔴 <b>Missing Mandatory Skills:</b>\n"
        for s in match["missing_required"]:
            detail_msg += f"  • {html.escape(s.title())}\n"
        detail_msg += "\n"

    if match.get("missing_preferred"):
        detail_msg += "🟡 <b>Missing Preferred Skills:</b>\n"
        for s in match["missing_preferred"]:
            detail_msg += f"  • {html.escape(s.title())}\n"

    await query.message.reply_text(detail_msg, parse_mode=constants.ParseMode.HTML)


async def process_batch_ranking(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    resumes_list: list,
    jd_text: str
):
    """Evaluates multiple candidate resumes and outputs leaderboard with best pick."""
    valid_resumes = [r for r in resumes_list if os.path.exists(r.get("path", ""))]
    if len(valid_resumes) == 0:
        await update.message.reply_text("❌ No valid resume files found in session. Please re-upload your files.")
        return

    progress_msg = await update.message.reply_text(
        f"⏳ <b>Ranking {len(valid_resumes)} Candidates with Gemini AI...</b>\n"
        "• Parsing candidate qualifications & resumes...\n"
        "• Matching against job description...\n"
        "• Selecting the #1 Best Match...",
        parse_mode=constants.ParseMode.HTML
    )

    try:
        await update.message.reply_chat_action(constants.ChatAction.TYPING)

        # Pass resumes list containing real uploaded file names
        ranking = rank_resumes(valid_resumes, jd_text)
        top = ranking["top_pick"]
        leaderboard = ranking["leaderboard"]
        context.user_data["cached_leaderboard"] = leaderboard

        try:
            await progress_msg.delete()
        except Exception:
            pass

        role_escaped = html.escape(str(ranking.get('target_role', 'Target Role')))
        top_name_escaped = html.escape(str(top['candidate_name']))
        top_file_escaped = html.escape(str(top['filename']))
        top_status_escaped = html.escape(str(top['status']))
        top_bd = top.get("breakdown", {})
        top_exp = top_bd.get("experience", {}).get("detected_years", 0)
        top_contact = top.get("contact", {})

        contact_parts = []
        if top_contact.get("email"):
            contact_parts.append(f"📧 {html.escape(top_contact['email'])}")
        if top_contact.get("phone"):
            contact_parts.append(f"📱 {html.escape(top_contact['phone'])}")
        top_contact_str = " | ".join(contact_parts) if contact_parts else "None listed"

        top_score_bar = format_progress_bar(top['score'], 100, 10)

        # Build clean formatted leaderboard
        report = (
            f"🏆 <b>CANDIDATE RANKING LEADERBOARD</b>\n"
            f"<b>Role:</b> {role_escaped}\n"
            f"<b>Candidates Evaluated:</b> {ranking['total_evaluated']}\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🥇 <b>#1 BEST RESUME MATCH:</b> <b>{top_name_escaped.upper()}</b>\n"
            f"• <b>Score:</b> <b>{top['score']}/100</b> ({top_status_escaped})\n"
            f"• <b>ATS Gauge:</b> <code>[{top_score_bar}]</code>\n"
            f"• <b>Uploaded File:</b> <code>{top_file_escaped}</code>\n"
            f"• <b>Experience:</b> ~{top_exp} years detected\n"
            f"• <b>Mandatory Skills Matched:</b> {len(top['matched_required'])}\n"
            f"• <b>Contact:</b> {top_contact_str}\n"
            f"• <b>Hiring Verdict:</b> <i>{html.escape(top['recommendation'])}</i>\n\n"
            "📊 <b>CANDIDATE LEADERBOARD:</b>\n"
        )

        for c in leaderboard:
            rank_icon = "🥇" if c['rank'] == 1 else ("🥈" if c['rank'] == 2 else ("🥉" if c['rank'] == 3 else f"#{c['rank']}"))
            c_name = html.escape(str(c['candidate_name']))
            c_file = html.escape(str(c['filename']))
            c_status = html.escape(str(c['status']))
            c_bd = c.get("breakdown", {})
            c_exp = c_bd.get("experience", {}).get("detected_years", 0)
            c_bar = format_progress_bar(c['score'], 100, 8)
            report += (
                f"{rank_icon} <b>{c_name}</b> — <b>{c['score']}/100</b>\n"
                f"   <code>[{c_bar}]</code>\n"
                f"   Doc: <code>{c_file}</code> | ~{c_exp} yrs exp | {c_status}\n\n"
            )

        # Probing recommendations for recruiters
        report += "💡 <b>RECRUITER INTERVIEW PROBING TIPS:</b>\n"
        for c in leaderboard[:3]:
            if c.get("missing_required"):
                c_name_short = html.escape(str(c['candidate_name']))
                missing_str = ", ".join([html.escape(s.title()) for s in c['missing_required'][:2]])
                report += f"• <b>{c_name_short}:</b> Ask about exposure to <i>{missing_str}</i>.\n"
            else:
                c_name_short = html.escape(str(c['candidate_name']))
                report += f"• <b>{c_name_short}:</b> 100% mandatory skills satisfied. Focus on depth & culture.\n"

        # Interactive inspection buttons
        keyboard = []
        row = []
        for c in leaderboard[:4]:
            cand_num = c["rank"]
            short_name = c["candidate_name"][:12]
            row.append(InlineKeyboardButton(f"🔍 #{cand_num} {short_name}", callback_data=f"cand_{cand_num}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("🔄 Start New Batch", callback_data="reset")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await send_smart_chunks(update, report, reply_markup=reply_markup)

        # Deliver downloadable full ranking report document
        report_bytes = io.BytesIO(ranking["report_markdown"].encode("utf-8"))
        report_bytes.name = "Candidate_Ranking_Report.md"
        await update.message.reply_document(
            document=report_bytes,
            filename="Candidate_Ranking_Report.md",
            caption="📥 <b>Download Complete Candidate Ranking Report (.md)</b>",
            parse_mode=constants.ParseMode.HTML
        )

        cleanup_session_resumes(context)

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
    resume_item: Union[Dict[str, str], str],
    jd_text: str
):
    """Processes single resume evaluation."""
    if isinstance(resume_item, dict):
        resume_path = resume_item.get("path", "")
        resume_name = resume_item.get("name") or Path(resume_path).name
    else:
        resume_path = str(resume_item)
        resume_name = context.user_data.get("resume_name") or Path(resume_path).name

    progress_msg = await update.message.reply_text(
        f"⏳ <b>Analyzing {html.escape(resume_name)} with Gemini AI...</b>\n"
        "• Extracting candidate profile & skills...\n"
        "• Evaluating job requirements...\n"
        "• Running 6-dimensional ATS scoring...",
        parse_mode=constants.ParseMode.HTML
    )

    try:
        await update.message.reply_chat_action(constants.ChatAction.TYPING)

        # 1. Parse Resume
        resume_text, resume_data = parse_resume(resume_path)
        cand_name = extract_candidate_name(resume_data, resume_text, resume_name)
        contact = resume_data.get("contact", {}) or {}

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

        if score >= 85:
            verdict = "🌟 Top Tier Match (Interview Ready)"
        elif score >= 70:
            verdict = "🟢 Strong Fit (Minor Polish Recommended)"
        elif score >= 50:
            verdict = "🟡 Moderate Fit (Review Key Skill Gaps)"
        else:
            verdict = "🔴 Low Fit (Needs Significant Tailoring)"

        score_bar = format_progress_bar(score, 100, 10)
        role_name = html.escape(str(jd_data.get('job_title', 'Target Role')))
        cand_name_escaped = html.escape(cand_name)
        file_name_escaped = html.escape(resume_name)

        contact_parts = []
        if contact.get("email"):
            contact_parts.append(f"📧 {html.escape(contact['email'])}")
        if contact.get("phone"):
            contact_parts.append(f"📱 {html.escape(contact['phone'])}")
        if contact.get("location"):
            contact_parts.append(f"📍 {html.escape(contact['location'])}")
        contact_line = f"📞 <b>Contact:</b> {' | '.join(contact_parts)}\n" if contact_parts else ""

        report = (
            f"🎯 <b>ATS MATCH REPORT: {score}/100</b> {score_emoji}\n"
            f"👤 <b>Candidate:</b> <b>{cand_name_escaped}</b>\n"
            f"📄 <b>Document:</b> <code>{file_name_escaped}</code>\n"
            f"💼 <b>Target Role:</b> <b>{role_name}</b>\n"
            f"🌟 <b>Fit Verdict:</b> <b>{verdict}</b>\n"
            f"{contact_line}"
            f"📊 <b>ATS Gauge:</b> <code>[{score_bar}]</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📋 <b>6-DIMENSIONAL SCORE BREAKDOWN:</b>\n"
            f"• Required Skills: <b>{bd['required_skills']['score']}/{bd['required_skills']['max']}</b> <code>[{format_progress_bar(bd['required_skills']['score'], bd['required_skills']['max'], 8)}]</code>\n"
            f"• Preferred Skills: <b>{bd['preferred_skills']['score']}/{bd['preferred_skills']['max']}</b> <code>[{format_progress_bar(bd['preferred_skills']['score'], bd['preferred_skills']['max'], 8)}]</code>\n"
            f"• Experience Match: <b>{bd['experience']['score']}/{bd['experience']['max']}</b> (Detected ~{bd['experience']['detected_years']} yrs)\n"
            f"• Education Fit: <b>{bd['education']['score']}/{bd['education']['max']}</b>\n"
            f"• Resume Structure: <b>{bd['structure']['score']}/{bd['structure']['max']}</b>\n"
            f"• Keywords Coverage: <b>{bd['keywords']['score']}/{bd['keywords']['max']}</b>\n\n"
        )

        # Matched Core Competencies
        matched_all = ats_result.get("matched_required", []) + ats_result.get("matched_preferred", [])
        if matched_all:
            report += f"✅ <b>MATCHED CORE COMPETENCIES ({len(matched_all)}):</b>\n"
            report += "  " + ", ".join([f"<code>{html.escape(s.title())}</code>" for s in matched_all[:12]]) + "\n\n"

        # Skill Gap Analysis
        report += "🔍 <b>SKILL GAP ANALYSIS:</b>\n"
        if ats_result["missing_required"]:
            report += "🔴 <b>Missing Mandatory Skills:</b>\n"
            for s in ats_result["missing_required"]:
                report += f"  • {html.escape(s.title())}\n"
        else:
            report += "🔴 <b>Missing Mandatory Skills:</b> None! Perfect match 🎉\n"

        if ats_result["missing_preferred"]:
            report += "\n🟡 <b>Missing Preferred Skills:</b>\n"
            for s in ats_result["missing_preferred"]:
                report += f"  • {html.escape(s.title())}\n"
        else:
            report += "\n🟡 <b>Missing Preferred Skills:</b> None! All covered 🎉\n"

        # High-Impact Actionable Improvements
        crit = improvements.get("critical_improvements", [])
        if crit:
            report += "\n💡 <b>HIGH-IMPACT RESUME ENHANCEMENTS:</b>\n"
            for idx, item in enumerate(crit[:3], 1):
                sec_escaped = html.escape(str(item.get('section', 'General')))
                sug_escaped = html.escape(str(item.get('suggestion', '')))
                ex_escaped = html.escape(str(item.get('example_transformation', '')))
                report += (
                    f"<b>{idx}. {sec_escaped}:</b> {sug_escaped}\n"
                    f"<i>Example Rewrite:</i>\n<code>{ex_escaped}</code>\n\n"
                )

        # Learning Paths
        if courses:
            report += "📚 <b>RECOMMENDED LEARNING ROADMAP:</b>\n"
            for c in courses[:3]:
                c_title = html.escape(str(c.get('course', '')))
                c_skill = html.escape(str(c.get('skill', '')).title())
                c_plat = html.escape(str(c.get('platform', '')))
                url_part = f" (<a href='{c['url']}'>Link</a>)" if c.get("url") else ""
                report += (
                    f"• <b>{c_title}</b>\n"
                    f"  Skill: <i>{c_skill}</i> | Platform: {c_plat}{url_part}\n"
                )

        # Quick action buttons
        keyboard = [
            [
                InlineKeyboardButton("🏆 Rank Multiple Resumes", callback_data="rank_info"),
                InlineKeyboardButton("🔄 Test Another Resume", callback_data="reset"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await send_smart_chunks(update, report, reply_markup=reply_markup)

        # Send downloadable Markdown report
        try:
            md_report = generate_markdown_report(
                resume_name=resume_name,
                jd_title=jd_data.get("job_title", "Target Role"),
                ats_result=ats_result,
                improvements=improvements,
                courses=courses,
                candidate_name=cand_name,
                contact=contact,
            )
            safe_doc_name = f"{Path(resume_name).stem}_ATS_Report.md"
            report_bytes = io.BytesIO(md_report.encode("utf-8"))
            report_bytes.name = safe_doc_name
            await update.message.reply_document(
                document=report_bytes,
                filename=safe_doc_name,
                caption=f"📥 <b>Download Complete ATS Report for {cand_name_escaped} (.md)</b>",
                parse_mode=constants.ParseMode.HTML
            )
        except Exception as doc_exc:
            logger.warning("Could not send report document: %s", doc_exc)

        cleanup_session_resumes(context)

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
    app.add_handler(CommandHandler("single", single_command_handler))
    app.add_handler(CommandHandler("rank", rank_command_handler))

    app.add_handler(CallbackQueryHandler(help_handler, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(reset_handler, pattern="^reset$"))
    app.add_handler(CallbackQueryHandler(single_command_handler, pattern="^single_mode$"))
    app.add_handler(CallbackQueryHandler(rank_command_handler, pattern="^rank_info$"))
    app.add_handler(CallbackQueryHandler(candidate_detail_callback, pattern="^cand_\\d+$"))

    # Accept all documents and validate PDF/DOCX/TXT extension safely
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

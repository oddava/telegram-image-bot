import logging
from datetime import datetime, timedelta, timezone
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.i18n import gettext as _
from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import User, ImageProcessingJob, ProcessingStatus

router = Router(name="history")
logger = logging.getLogger(__name__)

# Constants
JOBS_PER_PAGE = 5
RECENT_HOURS = 24


async def get_recent_jobs(session: AsyncSession, user_id: int, page: int = 0):
    """Get recent jobs for user with pagination"""
    offset = page * JOBS_PER_PAGE

    # Get jobs from last 24 hours, ordered by creation time
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=RECENT_HOURS)

    stmt = (
        select(ImageProcessingJob)
        .where(
            and_(
                ImageProcessingJob.user_id == user_id,
                ImageProcessingJob.created_at >= cutoff_time,
            )
        )
        .order_by(desc(ImageProcessingJob.created_at))
        .limit(JOBS_PER_PAGE)
        .offset(offset)
    )

    result = await session.execute(stmt)
    jobs = result.scalars().all()

    return jobs


async def count_recent_jobs(session: AsyncSession, user_id: int) -> int:
    """Count total recent jobs for pagination"""
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=RECENT_HOURS)

    stmt = (
        select(ImageProcessingJob)
        .where(
            and_(
                ImageProcessingJob.user_id == user_id,
                ImageProcessingJob.created_at >= cutoff_time,
            )
        )
    )

    result = await session.execute(stmt)
    return len(result.scalars().all())


def get_status_emoji(status: ProcessingStatus) -> str:
    """Get emoji for job status"""
    status_map = {
        ProcessingStatus.PENDING: "⏳",
        ProcessingStatus.PROCESSING: "⚙️",
        ProcessingStatus.COMPLETED: "✅",
        ProcessingStatus.FAILED: "❌",
    }
    return status_map.get(status, "❓")


def format_job_info(job: ImageProcessingJob, index: int) -> str:
    """Format single job information"""
    status_emoji = get_status_emoji(job.status)
    time_ago = get_time_ago(job.created_at)

    # Extract filename (remove path)
    filename = job.original_filename.split("/")[-1]
    if len(filename) > 30:
        filename = filename[:27] + "..."

    return (
        f"{index}. {status_emoji} *{filename}*\n"
        f"   Status: {job.status.value}\n"
        f"   Created: {time_ago}\n"
        f"   Job ID: `{job.id}`"
    )


def get_time_ago(dt: datetime) -> str:
    """Get human-readable time difference"""
    now = datetime.now(timezone.utc)
    diff = now - dt

    if diff.days > 0:
        return f"{diff.days}d ago"
    elif diff.seconds >= 3600:
        hours = diff.seconds // 3600
        return f"{hours}h ago"
    elif diff.seconds >= 60:
        minutes = diff.seconds // 60
        return f"{minutes}m ago"
    else:
        return "just now"


def create_history_keyboard(page: int, total_jobs: int, has_pending: bool) -> InlineKeyboardMarkup:
    """Create keyboard for history navigation"""
    buttons = []

    # Batch process button (only if there are pending jobs)
    if has_pending:
        buttons.append([
            InlineKeyboardButton(
                text="🔄 Process All Pending",
                callback_data=f"batch:process_all:{page}"
            )
        ])

    # Pagination buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(text="⬅️ Previous", callback_data=f"history:page:{page - 1}")
        )

    total_pages = (total_jobs + JOBS_PER_PAGE - 1) // JOBS_PER_PAGE
    if page < total_pages - 1:
        nav_buttons.append(
            InlineKeyboardButton(text="Next ➡️", callback_data=f"history:page:{page + 1}")
        )

    if nav_buttons:
        buttons.append(nav_buttons)

    # Refresh button
    buttons.append([
        InlineKeyboardButton(text="🔄 Refresh", callback_data=f"history:page:{page}")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def create_job_action_keyboard(job_id: str) -> InlineKeyboardMarkup:
    """Create keyboard for individual job actions"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🖼️ Remove BG",
                    callback_data=f"toggle:bg:{job_id}"
                ),
                InlineKeyboardButton(
                    text="🎨 As Sticker",
                    callback_data=f"toggle:sticker:{job_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="▶️ Process",
                    callback_data=f"process:start:{job_id}"
                ),
            ],
        ]
    )


@router.message(Command("history"))
async def handle_history_command(
        message: Message,
        user: User,
        session: AsyncSession,
):
    """Show user's recent processing history"""
    jobs = await get_recent_jobs(session, user.id, page=0)
    total_jobs = await count_recent_jobs(session, user.id)

    if not jobs:
        return await message.answer(
            _("📋 No recent jobs found.\n\n"
              "Upload an image to get started!")
        )

    # Check if there are pending jobs
    has_pending = any(job.status == ProcessingStatus.PENDING for job in jobs)

    # Format job list
    job_lines = [format_job_info(job, i + 1) for i, job in enumerate(jobs)]
    jobs_text = "\n\n".join(job_lines)

    # Create message
    text = (
        f"📋 *Your Recent Jobs* (Last {RECENT_HOURS}h)\n"
        f"Total: {total_jobs} | Page: 1/{(total_jobs + JOBS_PER_PAGE - 1) // JOBS_PER_PAGE}\n\n"
        f"{jobs_text}"
    )

    keyboard = create_history_keyboard(0, total_jobs, has_pending)

    await message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=keyboard
    )


@router.callback_query(F.data.startswith("history:page:"))
async def handle_history_page(
        callback: CallbackQuery,
        user: User,
        session: AsyncSession,
):
    """Handle history pagination"""
    try:
        page = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer("❌ Invalid page number")
        return

    jobs = await get_recent_jobs(session, user.id, page=page)
    total_jobs = await count_recent_jobs(session, user.id)

    if not jobs:
        await callback.answer("No jobs on this page")
        return

    has_pending = any(job.status == ProcessingStatus.PENDING for job in jobs)

    # Format job list
    job_lines = [format_job_info(job, page * JOBS_PER_PAGE + i + 1) for i, job in enumerate(jobs)]
    jobs_text = "\n\n".join(job_lines)

    # Create message
    text = (
        f"📋 *Your Recent Jobs* (Last {RECENT_HOURS}h)\n"
        f"Total: {total_jobs} | Page: {page + 1}/{(total_jobs + JOBS_PER_PAGE - 1) // JOBS_PER_PAGE}\n\n"
        f"{jobs_text}"
    )

    keyboard = create_history_keyboard(page, total_jobs, has_pending)

    try:
        await callback.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    except Exception:
        # Message content hasn't changed
        pass

    await callback.answer()


@router.callback_query(F.data.startswith("batch:process_all:"))
async def handle_batch_process(
        callback: CallbackQuery,
        user: User,
        session: AsyncSession,
):
    """Process all pending jobs with same options"""
    try:
        page = int(callback.data.split(":")[-1])
    except ValueError:
        page = 0

    # Get all pending jobs for this user
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=RECENT_HOURS)

    stmt = (
        select(ImageProcessingJob)
        .where(
            and_(
                ImageProcessingJob.user_id == user.id,
                ImageProcessingJob.status == ProcessingStatus.PENDING,
                ImageProcessingJob.created_at >= cutoff_time,
            )
        )
        .order_by(desc(ImageProcessingJob.created_at))
    )

    result = await session.execute(stmt)
    pending_jobs = result.scalars().all()

    if not pending_jobs:
        await callback.answer("No pending jobs to process", show_alert=True)
        return

    # Show batch options selection
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🖼️ Remove BG Only",
                    callback_data=f"batch:options:bg:{page}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎨 Sticker Only",
                    callback_data=f"batch:options:sticker:{page}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✅ Both (BG + Sticker)",
                    callback_data=f"batch:options:both:{page}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Back to History",
                    callback_data=f"history:page:{page}"
                ),
            ],
        ]
    )

    await callback.message.edit_text(
        f"🔄 *Batch Processing*\n\n"
        f"Found {len(pending_jobs)} pending jobs.\n"
        f"Choose processing options for all:",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

    await callback.answer()


@router.callback_query(F.data.startswith("batch:options:"))
async def handle_batch_options(
        callback: CallbackQuery,
        user: User,
        session: AsyncSession,
):
    """Execute batch processing with selected options"""
    from bot.services.task_publisher import publish_processing_task
    import json

    parts = callback.data.split(":")
    option = parts[2]  # "bg", "sticker", or "both"
    page = int(parts[3])

    # Determine options
    if option == "bg":
        options = {"remove_bg": True, "as_sticker": False}
        status_text = "🖼️ Remove Background"
    elif option == "sticker":
        options = {"remove_bg": False, "as_sticker": True}
        status_text = "🎨 Convert to Sticker"
    else:  # both
        options = {"remove_bg": True, "as_sticker": True}
        status_text = "✅ Remove BG + Sticker"

    # Get all pending jobs
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=RECENT_HOURS)

    stmt = (
        select(ImageProcessingJob)
        .where(
            and_(
                ImageProcessingJob.user_id == user.id,
                ImageProcessingJob.status == ProcessingStatus.PENDING,
                ImageProcessingJob.created_at >= cutoff_time,
            )
        )
    )

    result = await session.execute(stmt)
    pending_jobs = result.scalars().all()

    if not pending_jobs:
        await callback.answer("No pending jobs found", show_alert=True)
        return

    # Check quota
    db_user = await session.get(User, user.id)
    remaining = db_user.quota_limit - db_user.quota_used

    if remaining < len(pending_jobs):
        await callback.answer(
            f"❌ Not enough credits! Need {len(pending_jobs)}, have {remaining}",
            show_alert=True
        )
        return

    # Update quota
    db_user.quota_used += len(pending_jobs)

    # Process all jobs
    options["user_tier"] = user.tier.value

    for job in pending_jobs:
        job.processing_options = json.dumps(options)
        job.status = ProcessingStatus.PENDING
        job.updated_at = datetime.now(timezone.utc)

        # Publish to queue
        await publish_processing_task(str(job.id), options)

    await session.commit()

    remaining_after = db_user.quota_limit - db_user.quota_used

    await callback.message.edit_text(
        f"✅ *Batch Processing Started!*\n\n"
        f"Processing: {status_text}\n"
        f"Jobs queued: {len(pending_jobs)}\n"
        f"Remaining credits: {remaining_after}\n\n"
        f"You'll receive results shortly.",
        parse_mode="Markdown"
    )

    await callback.answer()
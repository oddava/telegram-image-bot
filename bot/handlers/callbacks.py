import json
import uuid
from datetime import datetime, timezone
from aiogram import Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import User, ImageProcessingJob, ProcessingStatus
from bot.services.task_publisher import publish_processing_task
from aiogram.utils.i18n import gettext as _

router = Router(name="callbacks")
router.callback_query.filter(lambda c: c.data and (c.data.startswith("process:") or c.data.startswith("toggle:")))


def parse_callback_data(callback_data: str) -> tuple[str, str, uuid.UUID]:
    """Parse callback data into action type, action, and job_id"""
    parts = callback_data.split(":")
    if len(parts) < 3:
        raise ValueError("Invalid callback data format")

    action_type = parts[0]  # "process" or "toggle"
    action = parts[1]
    job_id = uuid.UUID(parts[2])

    return action_type, action, job_id


def create_updated_keyboard(job_id: uuid.UUID, options: dict) -> InlineKeyboardMarkup:
    """Create keyboard with updated toggle states"""
    remove_bg = options.get("remove_bg", False)
    as_sticker = options.get("as_sticker", False)

    bg_text = "✅ Remove BG" if remove_bg else "🖼️ Remove BG"
    sticker_text = "✅ As Sticker" if as_sticker else "🎨 As Sticker"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=bg_text,
                    callback_data=f"toggle:bg:{job_id}"
                ),
                InlineKeyboardButton(
                    text=sticker_text,
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


async def get_job_options(job: ImageProcessingJob) -> dict:
    """Get current processing options from job"""
    try:
        return json.loads(job.processing_options)
    except (json.JSONDecodeError, TypeError):
        return {"remove_bg": False, "as_sticker": False}


async def update_job_options(job: ImageProcessingJob, options: dict):
    """Update job processing options"""
    job.processing_options = json.dumps(options)
    job.updated_at = datetime.now(timezone.utc)


async def handle_toggle(
        callback: CallbackQuery,
        job: ImageProcessingJob,
        action: str,
) -> None:
    """Handle toggle button clicks"""
    options = await get_job_options(job)

    # Toggle the option
    if action == "bg":
        options["remove_bg"] = not options.get("remove_bg", False)
    elif action == "sticker":
        options["as_sticker"] = not options.get("as_sticker", False)

    # Update job options (will be saved when processing starts)
    await update_job_options(job, options)

    # Update keyboard to show new state
    keyboard = create_updated_keyboard(job.id, options)

    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    except Exception:
        # Message might be too old to edit
        pass

    await callback.answer()


async def handle_process_start(
        callback: CallbackQuery,
        user: User,
        job: ImageProcessingJob,
        session: AsyncSession,
) -> None:
    """Handle process start button click"""
    # Get current options
    options = await get_job_options(job)

    # Check if at least one option is selected
    if not options.get("remove_bg") and not options.get("as_sticker"):
        await callback.answer("⚠️ Please select at least one option!", show_alert=True)
        return

    # Add metadata
    options["user_tier"] = user.tier.value
    options["telegram_message_id"] = callback.message.message_id

    # Get user from DB for quota update
    db_user = await session.get(User, user.id)
    if not db_user:
        await callback.message.answer(_("❌ User not found"))
        return

    # Increment quota
    db_user.quota_used += 1

    # Update job
    job.processing_options = json.dumps(options)
    job.status = ProcessingStatus.PENDING
    job.updated_at = datetime.now(timezone.utc)

    # Commit both updates
    await session.commit()

    # Publish to processing queue
    await publish_processing_task(str(job.id), options)

    remaining = db_user.quota_limit - db_user.quota_used

    # Build status message
    status_parts = []
    if options.get("remove_bg"):
        status_parts.append("🖼️ Remove Background")
    if options.get("as_sticker"):
        status_parts.append("🎨 Convert to Sticker")

    status_text = " + ".join(status_parts)

    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(
        _("✅ Processing started: {status}\n\n"
          "Job ID: {job_id}\n"
          "Remaining credits: {remaining}").format(
            status=status_text,
            job_id=job.id,
            remaining=remaining
        )
    )

    await callback.answer()


@router.callback_query()
async def handle_processing_callback(
        callback: CallbackQuery,
        user: User,
        session: AsyncSession,
):
    """Handle processing option selection"""
    try:
        action_type, action, job_id = parse_callback_data(callback.data)
    except (ValueError, IndexError):
        await callback.answer(_("❌ Invalid callback data"), show_alert=True)
        return

    # Get job
    job = await session.get(ImageProcessingJob, job_id)
    if not job or job.user_id != user.id:
        await callback.answer(_("❌ Job not found or access denied"), show_alert=True)
        return

    # Route to appropriate handler
    if action_type == "toggle":
        await handle_toggle(callback, job, action)
        await session.commit()
    elif action_type == "process" and action == "start":
        await handle_process_start(callback, user, job, session)
    else:
        await callback.answer(_("❌ Unknown action"), show_alert=True)
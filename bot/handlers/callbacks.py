import uuid
from datetime import datetime, timezone
from aiogram import Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from shared.models import User, ImageProcessingJob, ProcessingStatus
from ..services.task_publisher import publish_processing_task

router = Router(name="callbacks")
router.callback_query.filter(lambda c: c.data and c.data.startswith("process:"))


@router.callback_query()
async def handle_processing_callback(
        callback: CallbackQuery,
        user: User,
        session: AsyncSession,
):
    from aiogram.utils.i18n import gettext as _

    """Handle processing option selection"""
    await callback.answer()

    # Parse callback data
    parts = callback.data.split(":")

    if len(parts) < 3:
        return await callback.message.answer(_("❌ Invalid callback data"))

    action_type = parts[0]  # "process" or "format"
    action = parts[1]
    job_id_str = parts[2]

    try:
        job_id = uuid.UUID(job_id_str)
    except ValueError:
        return await callback.message.answer(_("❌ Invalid job ID"))

    # Get job
    job = await session.get(ImageProcessingJob, job_id)
    if not job or job.user_id != user.id:
        return await callback.message.answer(_("❌ Job not found or access denied"))

    # Handle convert submenu (show format options)
    if action == "convert" and action_type == "process":
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="PNG", callback_data=f"format:png:{job_id}"),
                    InlineKeyboardButton(text="JPEG", callback_data=f"format:jpg:{job_id}"),
                    InlineKeyboardButton(text="WebP", callback_data=f"format:webp:{job_id}"),
                ],
                [InlineKeyboardButton(text="🔙 Back", callback_data=f"process:bg:{job_id}")],
            ]
        )
        return await callback.message.edit_reply_markup(reply_markup=keyboard)

    # Prepare processing options
    action_map = {
        "bg": "remove_background",
        "resize": "resize",
        "batch": "batch",
    }

    # Handle format conversion
    if action_type == "format":
        target_format = action  # "png", "jpg", or "webp"
        options = {
            "action": "format_conversion",
            "target_format": target_format,
            "user_tier": user.tier.value,
            "telegram_message_id": callback.message.message_id,
        }
    else:
        options = {
            "action": action_map.get(action, action),
            "user_tier": user.tier.value,
            "telegram_message_id": callback.message.message_id,
        }

    # Fetch fresh user from THIS session
    db_user = await session.get(User, user.id)
    if not db_user:
        return await callback.message.answer(_("❌ User not found"))

    print(f"DEBUG: Before increment - User {db_user.id}, quota_used: {db_user.quota_used}")

    # Increment quota
    db_user.quota_used += 1

    print(f"DEBUG: After increment - User {db_user.id}, quota_used: {db_user.quota_used}")

    # Update job
    job.processing_options = str(options)
    job.status = ProcessingStatus.PENDING
    job.updated_at = datetime.now(timezone.utc)

    # Commit both updates
    await session.commit()

    print(f"DEBUG: After commit - User {db_user.id}, quota_used: {db_user.quota_used}")

    # Publish to processing queue
    await publish_processing_task(str(job.id), options)

    remaining = db_user.quota_limit - db_user.quota_used

    print(f"DEBUG: Remaining credits: {remaining}")

    await callback.message.answer(
        _("✅ Processing started! You'll receive the result shortly.\n\nJob ID: {job_id}\n"
          "Remaining credits: {remaining}").format(
            job_id=job.id,
            remaining=remaining
        )
    )
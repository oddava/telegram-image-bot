import uuid
from datetime import datetime, timezone
from aiogram import Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession

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

    x, action, job_id_str = callback.data.split(":")

    try:
        job_id = uuid.UUID(job_id_str)
    except ValueError:
        return await callback.message.answer(_("❌ Invalid job ID"))

    # Get job
    job = await session.get(ImageProcessingJob, job_id)
    if not job or job.user_id != user.id:
        return await callback.message.answer(_("❌ Job not found or access denied"))

    # Prepare processing options
    options = {
        "action": action,
        "user_tier": user.tier.value,
        "telegram_message_id": callback.message.message_id,
    }

    # Handle format selection submenu
    if action == "convert":
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

    elif action.startswith("format:"):
        _, fmt, _ = callback.data.split(":")
        options["target_format"] = fmt
        options["action"] = "format_conversion"

        # Increment quota for format conversion (separate operation)
        user.quota_used += 1
        await session.commit()

    # Publish to processing queue
    job.processing_options = str(options)
    job.status = ProcessingStatus.PENDING
    job.updated_at = datetime.now(timezone.utc)
    await session.commit()

    await publish_processing_task(str(job.id), options)

    # Increment quota for main operation
    if not action.startswith("format:"):
        user.quota_used += 1
        await session.commit()

    await callback.message.answer(
        _("✅ Processing started! You'll receive the result shortly.\n\nJob ID: {job_id}\n"
          "Remaining credits: {remaining}").format(
            job_id=job.id,
            remaining=user.quota_limit - user.quota_used
        )
    )
    return None
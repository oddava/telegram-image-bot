from datetime import datetime, timezone

from aiogram import Router, types
from aiogram.filters import CommandStart, Command
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import settings
from shared.models import User, UserTier


router = Router(name="commands")


@router.message(CommandStart())
async def cmd_start(message: types.Message, session: AsyncSession):
    # Register or update user
    user = await session.get(User, message.from_user.id)
    if not user:
        user = User(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
            tier=UserTier.FREE,
            quota_limit=settings.default_quota_free,
        )
        session.add(user)
        await session.commit()
        await message.answer(
            _("👋 Welcome! You have {quota} free image processing credits.").format(
                quota=settings.default_quota_free
            )
        )
    else:
        # Update user info
        user.username = message.from_user.username
        user.full_name = message.from_user.full_name
        user.last_seen = datetime.now(timezone.utc)
        await session.commit()
        await message.answer(
            _("🔄 Welcome back! You have {remaining} credits remaining.").format(
                remaining=user.quota_limit - user.quota_used
            )
        )

    await message.answer(
        _(
            "📸 Send me an image and I'll process it for you!\n\n"
            "Available commands:\n"
            "/help - Show help\n"
            "/quota - Check your quota\n"
            "/history - View recent processing jobs"
        )
    )


@router.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        _(
            "🛠️ <b>Image Processing Bot</b>\n\n"
            "<b>Features:</b>\n"
            "• Background removal\n"
            "• Format conversion (JPG, PNG, WebP)\n"
            "• Image resizing\n"
            "• Batch processing\n\n"
            "<b>Usage:</b>\n"
            "1. Send an image\n"
            "2. Choose processing options\n"
            "3. Wait for the result\n\n"
            "<b>Quota:</b> Free users get 10 images/day"
        ),
        parse_mode="HTML",
    )


@router.message(Command("quota"))
async def cmd_quota(message: types.Message, session: AsyncSession) -> None:
    user = await session.get(User, message.from_user.id)
    if not user:
        return await cmd_start(message, session)

    remaining = user.quota_limit - user.quota_used
    await message.answer(
        _("📊 <b>Your Quota</b>\n\nTier: {tier}\nUsed: {used}\nRemaining: {remaining}\nTotal: {total}").format(
            tier=user.tier.value, used=user.quota_used, remaining=remaining, total=user.quota_limit
        ),
        parse_mode="HTML",
    )
    return None
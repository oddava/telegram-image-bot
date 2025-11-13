from aiogram import Router, types
from aiogram.filters import CommandStart, Command
from aiogram.utils.i18n import gettext as _

from shared.models import User


router = Router(name="commands")


@router.message(CommandStart())
async def cmd_start(message: types.Message, user: User):
    # user is guaranteed to exist, since middleware creates it
    await message.answer(
        _("👋 Hello, {name}! You have {remaining} credits remaining.").format(
            name=user.full_name,
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
            "<b>Usage:</b>\n"
            "1. Send an image\n"
            "2. Choose processing options\n"
            "3. Wait for the result\n\n"
            "<b>Quota:</b> Free users get 10 images/day"
        ),
        parse_mode="HTML",
    )


@router.message(Command("quota"))
async def cmd_quota(message: types.Message, user: User) -> None:

    remaining = user.quota_limit - user.quota_used
    await message.answer(
        _("📊 <b>Your Quota</b>\n\nTier: {tier}\nUsed: {used}\nRemaining: {remaining}\nTotal: {total}").format(
            tier=user.tier.value, used=user.quota_used, remaining=remaining, total=user.quota_limit
        ),
        parse_mode="HTML",
    )
    return None
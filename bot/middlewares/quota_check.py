from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from aiogram.utils.i18n import gettext as _

from shared.models import User


class QuotaCheckMiddleware(BaseMiddleware):
    """Middleware to check user quotas before processing"""

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        user: User | None = data.get("user")

        if not user or user.tier in {"ADMIN", "PREMIUM"}:
            return await handler(event, data)

        if isinstance(event, Message) and (event.photo or event.document):
            if user.quota_used >= user.quota_limit:
                await event.answer(
                    _("❌ Quota exceeded!\n\n"
                      "Your limit: {limit} images/day\n"
                      "Used: {used}\n\n"
                      "Use /quota to check your usage").format(
                        limit=user.quota_limit,
                        used=user.quota_used,
                    )
                )
                return

        elif isinstance(event, CallbackQuery) and event.data and "process:" in event.data:
            if user.quota_used >= user.quota_limit:
                await event.answer(
                    _("❌ Quota exceeded!\n\n"
                      "Your limit: {limit} images/day\n"
                      "Used: {used}\n\n"
                      "Upgrade to premium for unlimited processing!").format(
                        limit=user.quota_limit,
                        used=user.quota_used,
                    ),
                    show_alert=True,
                )
                return

        return await handler(event, data)

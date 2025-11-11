from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Update
from aiogram.utils.i18n import gettext as _

from shared.models import User


class QuotaCheckMiddleware(BaseMiddleware):
    """Middleware to check user quotas before processing"""

    async def __call__(
            self,
            handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
            event: Update,
            data: Dict[str, Any],
    ) -> Any:
        user: User | None = data.get("user")

        # Skip quota check for admins and non-image operations
        if not user or user.tier in ["admin", "premium"]:
            return await handler(event, data)

        # Check quota only for photo/document messages and processing callbacks
        is_image_operation = (
                (event.message and (event.message.photo or event.message.document))
                or (event.callback_query and event.callback_query.data and "process:" in event.callback_query.data)
        )

        if is_image_operation and user.quota_used >= user.quota_limit:
            # Block operation and notify user
            if event.callback_query:
                await event.callback_query.answer(
                    _("❌ Quota exceeded!\n\n"
                      "Your limit: {limit} images/day\n"
                      "Used: {used}\n\n"
                      "Upgrade to premium for unlimited processing!").format(
                        limit=user.quota_limit, used=user.quota_used
                    ),
                    show_alert=True,
                )
            elif event.message:
                await event.message.answer(
                    _("❌ Quota exceeded!\n\n"
                      "Your limit: {limit} images/day\n"
                      "Used: {used}\n\n"
                      "Use /quota to check your usage").format(
                        limit=user.quota_limit, used=user.quota_used
                    )
                )
            return  # Block execution

        return await handler(event, data)
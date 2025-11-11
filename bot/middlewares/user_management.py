from typing import Callable, Dict, Any, Awaitable
from datetime import datetime
import logging

from aiogram import BaseMiddleware
from aiogram.types import Update, User as TelegramUser
from aiogram.utils.i18n import gettext as _
from sqlalchemy import select

from shared.database import async_session_maker
from shared.models import User, UserTier
from shared.config import settings

logger = logging.getLogger(__name__)


class UserManagementMiddleware(BaseMiddleware):
    """Middleware for automatic user registration and metadata tracking"""

    async def __call__(
            self,
            handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
            event: Update,
            data: Dict[str, Any],
    ) -> Any:
        # Extract telegram user from different event types
        telegram_user: TelegramUser | None = None

        if event.message:
            telegram_user = event.message.from_user
        elif event.callback_query:
            telegram_user = event.callback_query.from_user
        elif event.inline_query:
            telegram_user = event.inline_query.from_user
        elif event.my_chat_member:
            telegram_user = event.my_chat_member.from_user

        if not telegram_user:
            return await handler(event, data)

        # Get or create user in database
        async with async_session_maker() as session:
            result = await session.execute(select(User).where(User.telegram_id == telegram_user.id))
            user = result.scalar_one_or_none()

            if not user:
                user = User(
                    telegram_id=telegram_user.id,
                    username=telegram_user.username,
                    full_name=telegram_user.full_name or telegram_user.username or "User",
                    tier=UserTier.FREE,
                    quota_limit=settings.default_quota_free,
                    quota_used=0,
                    created_at=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    is_active=True,
                )
                session.add(user)
                try:
                    await session.commit()
                    await session.refresh(user)
                    logger.info(f"✅ New user registered: {user.telegram_id} (@{user.username})")

                    if event.message:
                        await event.message.answer(
                            _(
                                "👋 Welcome! You have {quota} free image processing credits.\n\n"
                                "Send me an image to get started!"
                            ).format(quota=settings.default_quota_free)
                        )
                except Exception as e:
                    await session.rollback()
                    logger.error(f"Failed to create user: {e}")
            else:
                user.last_seen = datetime.utcnow()
                user.is_active = True
                if user.username != telegram_user.username:
                    user.username = telegram_user.username
                if user.full_name != (telegram_user.full_name or telegram_user.username or "User"):
                    user.full_name = telegram_user.full_name or telegram_user.username or "User"
                await session.commit()

            data["user"] = user

        return await handler(event, data)
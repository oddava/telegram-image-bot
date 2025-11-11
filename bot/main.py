import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.utils.i18n import I18n
from aiogram.utils.i18n.middleware import I18nMiddleware

from shared.config import settings
from shared.database import engine, async_session_maker
from bot.handlers import commands, photo, callbacks
from bot.middlewares.user_management import UserManagementMiddleware
from bot.middlewares.quota_check import QuotaCheckMiddleware
from shared.models import Base

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize bot
bot = Bot(
    token=settings.bot_token,
    default=DefaultBotProperties(parse_mode="HTML"),
)

# Initialize dispatcher with Redis storage
dp = Dispatcher(storage=RedisStorage.from_url(settings.redis_url))

# Setup i18n
i18n = I18n(path="bot/locales", default_locale="en", domain="messages")

# Register global middlewares (order matters!)
dp.update.middleware(UserManagementMiddleware())

# Register quota middleware only for specific routers
photo.router.message.middleware(QuotaCheckMiddleware())
photo.router.callback_query.middleware(QuotaCheckMiddleware())
callbacks.router.callback_query.middleware(QuotaCheckMiddleware())

# Register routers
dp.include_router(commands.router)
dp.include_router(photo.router)
dp.include_router(callbacks.router)


async def setup_database():
    """Initialize database tables"""
    logger.info("Setting up database...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database setup complete!")


async def main():
    await setup_database()
    logger.info("🚀 Bot starting...")

    # Configure webhook or polling
    if settings.bot_webhook_url:
        # Webhook mode (production)
        from aiogram.webhook.aiohttp_server import SimpleRequestHandler
        from aiohttp import web

        app = web.Application()
        webhook_path = f"/{settings.bot_secret_token}" if settings.bot_secret_token else "/webhook"

        SimpleRequestHandler(
            dispatcher=dp,
            bot=bot,
            secret_token=settings.bot_secret_token,
        ).register(app, path=webhook_path)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=8080)
        await site.start()

        await bot.set_webhook(
            url=f"{settings.bot_webhook_url}{webhook_path}",
            secret_token=settings.bot_secret_token,
            allowed_updates=["message", "callback_query"],
        )
        logger.info(f"Webhook set to: {settings.bot_webhook_url}{webhook_path}")

        # Keep running
        await asyncio.Event().wait()
    else:
        # Polling mode (development)
        logger.info("Starting polling mode...")
        await dp.start_polling(
            bot,
            skip_updates=settings.bot_skip_updates,
            allowed_updates=["message", "callback_query"],
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped!")
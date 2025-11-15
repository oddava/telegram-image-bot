import asyncio

import uvloop
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage

from bot.handlers import router
from bot.middlewares import init_middlewares
from shared.config import settings
from shared.database import close_database, init_database, db
from loguru import logger

bot = Bot(
    token=settings.bot_token.get_secret_value(),
    default=DefaultBotProperties(parse_mode="HTML"),
)

dp = Dispatcher(storage=RedisStorage.from_url(settings.redis_url))


async def on_startup():
    await init_database(create_tables=True)
    if not await db.health_check():
        raise RuntimeError("DB not healthy")
    init_middlewares(dp)
    dp.include_router(router)

    bot_info = await bot.get_me()
    logger.info(f"Name     - {bot_info.full_name}")
    logger.info(f"Username - @{bot_info.username}")
    logger.info(f"ID       - {bot_info.id}")

    states = {
        True: "Enabled",
        False: "Disabled",
        None: "Unknown (Not a bot)",
    }

    logger.info(f"Groups Mode  - {states[bot_info.can_join_groups]}")
    logger.info(f"Privacy Mode - {states[not bot_info.can_read_all_group_messages]}")
    logger.info(f"Inline Mode  - {states[bot_info.supports_inline_queries]}")


async def on_shutdown():
    """Clean shutdown"""
    logger.info("Shutting down bot...")
    await close_database()
    await bot.delete_webhook(drop_pending_updates=False)

    await bot.session.close()
    logger.success("✅ Bot stopped successfully")


async def main():
    logger.info("🚀 Bot starting...")
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Configure webhook or polling
    if settings.use_webhook:
        from aiogram.webhook.aiohttp_server import SimpleRequestHandler
        from aiohttp import web

        app = web.Application()

        webhook_path = "/webhook"

        # Create handler WITH secret token for security
        # Telegram will send this token in the X-Telegram-Bot-Api-Secret-Token header
        SimpleRequestHandler(
            dispatcher=dp,
            bot=bot,
            handle_in_background=True,
            secret_token=settings.bot_secret_token,
        ).register(app, path=webhook_path)

        runner = web.AppRunner(app)
        await runner.setup()

        # Use configurable port (get from env or default to 8443)
        port = int(settings.webhook_port) if hasattr(settings, 'webhook_port') else 8443

        site = web.TCPSite(runner, host="0.0.0.0", port=port)
        await site.start()

        # Set webhook with HTTPS URL and secret token
        full_webhook_url = f"{settings.bot_webhook_url}{webhook_path}"
        logger.info(f"Setting webhook to: {full_webhook_url}")

        await bot.set_webhook(
            url=full_webhook_url,
            secret_token=settings.bot_secret_token.get_secret_value(),
            allowed_updates=["message", "callback_query"],
        )
        logger.success("✅ Webhook set successfully")

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
        uvloop.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped!")

from aiogram import Router

from bot.handlers import commands, photo, callbacks

router = Router()

router.include_router(commands.router)
router.include_router(photo.router)
router.include_router(callbacks.router)
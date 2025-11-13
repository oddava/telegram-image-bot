from aiogram import Dispatcher
from aiogram.utils.i18n import I18n

from shared.database import db
from .session import DatabaseMiddleware
from .i18n import CustomI18nMiddleware
from .user_management import UserManagementMiddleware
from .quota_check import QuotaCheckMiddleware
from bot.handlers import photo, callbacks

# Setup i18n
i18n = I18n(path="bot/locales", default_locale="en", domain="messages")

def init_middlewares(dp: Dispatcher):
    dp.update.middleware(CustomI18nMiddleware(i18n))

    dp.update.middleware(DatabaseMiddleware(db.session))

    # Register global middlewares (order matters!)
    dp.update.middleware(UserManagementMiddleware())

    # Register quota middleware only for specific routers
    photo.router.message.middleware(QuotaCheckMiddleware())
    photo.router.callback_query.middleware(QuotaCheckMiddleware())
    callbacks.router.callback_query.middleware(QuotaCheckMiddleware())
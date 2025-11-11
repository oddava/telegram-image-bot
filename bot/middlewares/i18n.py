from aiogram.utils.i18n import I18n
from aiogram.utils.i18n.middleware import I18nMiddleware
from aiogram.types import TelegramObject
from typing import Any, Dict, Optional



class CustomI18nMiddleware(I18nMiddleware):
    def __init__(self, i18n: I18n, i18n_key: Optional[str] = "i18n", middleware_key: str = "i18n_middleware") -> None:
        super().__init__(i18n, i18n_key, middleware_key)
        self.default_locale = i18n.default_locale

    async def get_locale(self, event: TelegramObject, data: Dict[str, Any]) -> str:
            return self.default_locale or "en"
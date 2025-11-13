import sys
from pathlib import Path
from loguru import logger as _logger

from shared.config import settings

# --- config ------------------------------------------------------------------
LOG_LEVEL      = "DEBUG" if settings.debug else "INFO"
LOG_FORMAT     = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)
JSON_LOGS      = not settings.debug   # structured logs in prod
LOG_FILE_PATH  = Path("logs/bot.jsonl")      # rotated automatically
# -----------------------------------------------------------------------------

# remove default handler
_logger.remove()

# console
_logger.add(
    sys.stdout,
    format=LOG_FORMAT,
    level=LOG_LEVEL,
    serialize=JSON_LOGS,          # False = human, True = JSON
    backtrace=False,              # no stack in prod
    diagnose=settings.debug,      # vars in tracebacks only in debug
)

LOG_FILE_PATH.parent.mkdir(exist_ok=True)
_logger.add(
    LOG_FILE_PATH,
    rotation="00:00",
    retention="14 days",
    serialize=True,
    level=LOG_LEVEL,
    compression="gz",
)

# export the configured logger
logger = _logger
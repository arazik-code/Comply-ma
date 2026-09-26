import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import settings

try:
    from pythonjsonlogger import jsonlogger
    HAS_JSON_LOGGER = True
except ImportError:
    HAS_JSON_LOGGER = False


def setup_logging():
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    if settings.log_format == "json" and HAS_JSON_LOGGER:
        fmt = jsonlogger.JsonFormatter(
            fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    else:
        fmt = logging.Formatter(
            "[%(asctime)s] %(levelname)-7s %(name)s \u2014 %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    handler.setFormatter(fmt)
    root.handlers.clear()
    root.addHandler(handler)

    log_dir = Path(settings.data_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / "comply-ma.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    logging.getLogger("app").info(
        "logging initialized",
        extra={"log_level": settings.log_level, "format": settings.log_format},
    )

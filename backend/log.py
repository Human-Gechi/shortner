import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from backend.config import get_settings


def setup_logging() -> None:
    settings = get_settings()
    level_name = settings.LOG_LEVEL
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    if root.handlers:
        return

    fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
    formatter = logging.Formatter(fmt)

    # Stream handler (console)
    sh = logging.StreamHandler()
    sh.setLevel(level)
    sh.setFormatter(formatter)
    root.addHandler(sh)

    # File handler (rotating)
    log_file = settings.LOG_FILE
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    fh = RotatingFileHandler(
        str(log_path), maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setLevel(level)
    fh.setFormatter(formatter)
    root.addHandler(fh)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

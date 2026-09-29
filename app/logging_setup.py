import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(root: Path, debug: bool = False) -> None:
    directory = root / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("localchat")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    if logger.handlers:
        return
    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    for handler in (logging.StreamHandler(), RotatingFileHandler(
            directory / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")):
        handler.setFormatter(formatter)
        logger.addHandler(handler)

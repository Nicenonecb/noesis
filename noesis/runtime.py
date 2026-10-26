"""Local process locking and private, redacted operational logs."""

from contextlib import contextmanager
from datetime import datetime
import fcntl
import logging
import os

from .config import private_directory
from .redact import redact


class AlreadyRunning(Exception):
    pass


@contextmanager
def collection_lock(root):
    """Shared by collect and the future build-daily command. Never unlink it."""
    private_directory(root / "run")
    fd = os.open(root / "run/collect.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AlreadyRunning("采集或日志生成正在运行，本次跳过。") from None
        yield
    finally:
        os.close(fd)


class PrivateLogHandler(logging.Handler):
    def __init__(self, config):
        super().__init__()
        self.config = config

    def emit(self, record):
        now = datetime.now(self.config.timezone)
        path = self.config.root / "logs" / f"noesis-{now:%Y-%m-%d}.log"
        message = redact(f"{now.isoformat()} {record.levelname} {record.getMessage()}")
        message = message.replace("\n", " ").replace("\r", " ")
        fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(message + "\n")


@contextmanager
def run_logger(config):
    private_directory(config.root / "logs")
    logger = logging.Logger("noesis.collect", level=logging.INFO)
    handler = PrivateLogHandler(config)
    logger.addHandler(handler)
    try:
        yield logger
    finally:
        logger.removeHandler(handler)
        handler.close()

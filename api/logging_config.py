import logging
import logging.handlers
from pathlib import Path


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 1 MB per file, keep the last 5
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(file_handler)

    # Silence noisy third-party loggers
    for noisy in ("openai", "httpx", "httpcore", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

# src/logger_setup.py
# Configura logging colorido no terminal + arquivo de log rotativo

import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler

import colorlog

import config


def setup(name: str = "pantheon") -> logging.Logger:
    os.makedirs(config.LOG_DIR, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger  # já configurado

    # ── Handler colorido para o terminal ─────────────────────────────────────
    stream_handler = colorlog.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s [%(levelname)s]%(reset)s %(message)s",
        datefmt="%H:%M:%S",
        log_colors={
            "DEBUG":    "cyan",
            "INFO":     "green",
            "WARNING":  "yellow",
            "ERROR":    "red",
            "CRITICAL": "bold_red",
        },
    ))

    # ── Handler de arquivo com rotação ────────────────────────────────────────
    log_file = os.path.join(
        config.LOG_DIR,
        f"coleta_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
    )
    file_handler = RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)

    # Propaga para módulos filhos
    logging.getLogger("src").setLevel(logging.DEBUG)
    logging.getLogger("src").addHandler(stream_handler)
    logging.getLogger("src").addHandler(file_handler)

    return logger

import os
import logging
from logging.handlers import TimedRotatingFileHandler
from web_backend.core.config import log_settings

logging_dir = log_settings.LOGGING_DIR
logging_filename = log_settings.FILE_NAME
logging_when = log_settings.WHEN
logging_interval = log_settings.INTERVAL
logging_backup = log_settings.BACKUP

logging_format = log_settings.FORMAT
logging_datefmt = log_settings.DATEFMT

os.makedirs(logging_dir, exist_ok = True)

logger = logging.getLogger("fastapi_logger")
logger.setLevel(logging.INFO)

formatter = logging.Formatter(
    fmt = logging_format,
    datefmt = logging_datefmt
)

file_handler = TimedRotatingFileHandler(
    filename = os.path.join(logging_dir, logging_filename),
    when = logging_when, # 자정에 새로운 로드 파일을 생성
    interval = logging_interval, # 새로운 로그 파일 갱신: logging_interval (1일) 마다
    backupCount = logging_backup # 저장기간: logging_backup (7일)
)

file_handler.setFormatter(formatter)

if not logger.hasHandlers():
    logger.addHandler(file_handler)
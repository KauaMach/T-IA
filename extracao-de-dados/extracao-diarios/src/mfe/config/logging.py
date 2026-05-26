import logging
import os
from typing import Dict, List, Tuple


class MessageSuppressionFilter(logging.Filter):
    """Custom filter to suppress specific log messages based on logger name and message content."""

    def __init__(self, suppression_rules: List[Dict[str, str]] = None):
        """
        Initialize the filter with suppression rules.

        Args:
            suppression_rules: List of dictionaries containing 'logger_name' and 'message_pattern'
                              to define which messages should be suppressed.
        """
        super().__init__()
        self.suppression_rules = suppression_rules or []

    def filter(self, record):
        """
        Filter method that returns False for messages that should be suppressed.

        Args:
            record: LogRecord instance

        Returns:
            bool: False if message should be suppressed, True otherwise
        """
        for rule in self.suppression_rules:
            logger_name = rule.get("logger_name", "")
            message_pattern = rule.get("message_pattern", "")

            # Check if both logger name and message pattern match
            if logger_name in record.name and message_pattern in record.getMessage():
                return False

        return True


def create_logger(
    name: str, level: int = logging.INFO, suppression_rules: List[Dict[str, str]] = None
) -> Tuple[logging.Logger, logging.Logger]:
    os.makedirs("./logs", exist_ok=True)

    if suppression_rules is None:
        suppression_rules = [
            {
                "logger_name": "docling.models.factories",
                "message_pattern": "Registered ocr engines: ['easyocr', 'ocrmac', 'rapidocr', 'tesserocr', 'tesseract']",
            },
            {
                "logger_name": "docling.models.factories",
                "message_pattern": "Loading plugin 'docling_defaults'",
            },
            {
                "logger_name": "docling.models.factories",
                "message_pattern": "Registered picture descriptions: ['vlm', 'api']",
            },
        ]

    message_filter = MessageSuppressionFilter(suppression_rules)

    file_handler = logging.FileHandler(os.path.join(".", "logs", f"{name}.log"))
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s")
    )
    file_handler.addFilter(message_filter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s")
    )
    console_handler.addFilter(message_filter)

    logger = logging.getLogger(name)

    if not logger.handlers:
        logger.setLevel(level)
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        logger.propagate = False

    error_logger = logging.getLogger(f"{name}_error")

    if not error_logger.handlers:
        error_logger.setLevel(logging.ERROR)

        error_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

        error_handler = logging.FileHandler(
            os.path.join(".", "logs", f"{name}_error.log")
        )
        error_handler.setFormatter(error_formatter)
        error_logger.addHandler(error_handler)
        error_logger.addHandler(console_handler)

    return logger, error_logger

import logging
import sys

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger handlers and format for the application.

    Args:
        level: Logging level (e.g., `logging.INFO`).
    """

    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        handlers=[
            logging.StreamHandler(sys.stdout),
            # logging.FileHandler(os.path.join("logs", "app.log")),
        ],
    )

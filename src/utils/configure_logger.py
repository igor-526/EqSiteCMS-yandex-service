import logging


def configure_logger(logger_root_name: str, logger_prefix_output: str) -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)

    logging.basicConfig(
        format=(f"{logger_prefix_output}:\n    %(name)s %(levelname)s %(asctime)s \n    MESSAGE: %(message)s"),
        level=logging.INFO,
    )

    logger = logging.getLogger(logger_root_name)
    logger.info("Logger has configured.")

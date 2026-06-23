import logging
from hw_tests.opkssh import OPKSSH
from hw_tests.cloudsmith import Cloudsmith

logger = logging.getLogger(__name__)


def main(context):
    logger.info(f"got {context}")

    OPKSSH()

    logger.info("opkssh auth done")
    # ssh {opkssh.host} 'echo "hello world!"'

    Cloudsmith()
    logger.info("cloudsmith auth done")

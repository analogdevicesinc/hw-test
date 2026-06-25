import logging


from hw_tests.cloudsmith import Cloudsmith

logger = logging.getLogger(__name__)


def test_linux_iio_dac(context):
    logger.info(f"got {context}")

    Cloudsmith()
    logger.info("cloudsmith auth done")

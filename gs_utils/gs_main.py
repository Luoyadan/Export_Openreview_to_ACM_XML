import os
import time
import logging
import logging.config
from src.fetch_data import (
    fetch_submission_metadata,
    fetch_review_wordcount,
    fetch_review_rating,
    fetch_missing_metareview,
    fetch_recommendation_outliers
)
from src.gs_upload import gs_ac_upload, gs_sac_upload
from src.utils import (
    load_credentials,
    get_client,
    authenticate_gspread,
)
from src.constants import SCRIPT_WAIT_PERIOD


# Load logging configuration
logging.config.fileConfig('logs/logging.conf')

# Access logger
logger = logging.getLogger(__name__)


def wait_step():
    logger.info(f"Waiting for {SCRIPT_WAIT_PERIOD} seconds before executing next step")
    time.sleep(SCRIPT_WAIT_PERIOD)


def main():
    load_credentials()
    client = get_client()
    gs_client, service = authenticate_gspread(
        os.environ['GOOGLE_CREDENTIALS_PATH'],
        os.environ['GOOGLE_REFRESH_TOKEN_PATH'],
        build_service=True
    )

    while True:
        # fetch the conference metadata first (PC -> SAC -> AC -> Reviewer assignments)
        fetch_submission_metadata(client)
        wait_step()

        # fetch the review word count data
        fetch_review_wordcount(client)
        wait_step()

        # fetch the review rating data
        fetch_review_rating(client)
        wait_step()

        # fetch the missing metareview of the AC's, for PC's analysis and review
        fetch_missing_metareview(client)
        wait_step()

        # fetch the AC's recommendation outliers, for PC's analysis and review
        fetch_recommendation_outliers(client)
        wait_step()

        # upload the area chair data to Google Sheets
        gs_ac_upload(gs_client)
        wait_step()

        # upload the senior area chair data to Google Sheets
        gs_sac_upload(gs_client, service)
        wait_step()


if __name__ == "__main__":
    main()

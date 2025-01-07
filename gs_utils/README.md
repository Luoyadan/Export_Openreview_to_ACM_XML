# OpenReview - Google Sheets Integration Setup for MM'24

## Overview
This repository contains the code for integrating OpenReview with Google Sheets for MM'24 conference. The integration allows for the automatic creation of Google Sheets for all submissions, and the automatic update of the sheets with the latest information from OpenReview for Area Chairs, Senior Area Chairs, and Program Chairs to use. Please go through the setup instructions below to get started and understand the functionalities of this integration.

## Setup
Install the required packages by running the following command:
```sh
conda env create -f environment.yml
conda activate openreview
```

To use this integration, you need to create a Google Sheet API project and enable corresponding extensions. To get the necessary credentials, please follow the instructions at https://docs.gspread.org/en/latest/oauth2.html#for-end-users-using-oauth-client-id and save the credential at the `GOOGLE_CREDENTIALS_PATH`.

Then, create an `.env` file in the project root and fill in the following information:
```sh
# The venue id assigned to your conference
OPENREVIEW_VENUE_ID='acmmm.org/CONFERENCE/YEAR/Conference'

# ---------- BELOW IS CONFIDENTIAL INFORMATION, DO NOT SHARE ----------
# Your OpenReview email and password
OPENREVIEW_USERNAME='OPENREVIEW_EMAIL'
OPENREVIEW_PASSWORD='OPENREVIEW_PASSWORD'

# Please refer to https://docs.gspread.org/en/latest/oauth2.html#for-end-users-using-oauth-client-id for instructions on how to obtain these credentials and tokens for Google APIs
# 1. GOOGLE_CREDENTIALS_PATH should be a JSON oauth credentials file from Google
GOOGLE_CREDENTIALS_PATH='./credentials/CREDENTIALS.json'
# 2. GOOGLE_REFRESH_TOKEN_PATH is the path pointing to the automatically generated refresh token from generate_refresh_token.py
GOOGLE_REFRESH_TOKEN_PATH='./credentials/REFRESH_TOKEN.refresh_token'
# 3. GOOGLE_ACCOUNT should be the gmail email address of the account you are using
GOOGLE_ACCOUNT='YOUR_EMAIL'
```

Next, run the `generate_refresh_token.py` code to generate the refresh token.

To start crawling the OpenReview data and updating the Google Sheets, run the following command:
```sh
python gs_main.py
```

To broadcast the Google Sheets link to corresponding chairs, run the following command:
```sh
python email_broadcast_main.py
```
Please keep in mind that some institutions may block the email sent from the script, so it is recommended to use the email functions from OpenReview platform.

To obtain all detailed information about submissions with at least one review, or understand the trends of review word counts over time, run the following command:
```sh
python comprehensive_data_main.py
```

## FAQs
### Frequent Backoff or Update Failures in Google Sheets, or Need for Faster Updates
Adjust the following configurations in the src/constants.py file to avoid rate limits and improve update speed: `API_CREATE_LIMIT`, `API_UPDATE_LIMIT`, `API_SHARE_LIMIT`, `WAIT_TIME`, and `SAC_API_SHEET_UPDATE_LIMIT`.

### Authentication Issues with Google Sheets API
If you encounter an expired authentication token or connection failures, renew the refresh token by running the `generate_refresh_token.py` script.

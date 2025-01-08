"""
This script can broadcast the Google Sheet link for each reviewer to access their review tracking spreadsheet by sending an email to each reviewer with their access link...

Important: Please note that many Chinese institutions block Google services and will refuse to receive emails from Gmail. So, we suggest you to use the email functionality from OpenReview platform instead.
"""
import os
import time
import json
import tqdm
from src.utils import load_credentials, get_gmail_service, send_email
from src.constants import CACHE_DIR, EMAIL_TEMPLATE, API_GMAIL_LIMIT, EMAIL_WAIT_TIME


def email_notify(gmail_service, from_email, user2gs, user_info, subject):
    for i, (user_id, gs_link) in enumerate(tqdm.tqdm(user2gs.items())):
        # to_email = 'acmmm2024pc@gmail.com'
        to_email = user_info[user_id]['email']

        user_name = user_info[user_id]['name']
        message = EMAIL_TEMPLATE.format(user_name, gs_link)

        # Send an email
        send_email(gmail_service, from_email, to_email, subject, message)
        print(f'Sent email to {to_email} - ({i + 1}/{len(user2gs)})')

        # Wait for buffer time
        time.sleep(0.5)

        # Long wait to avoid API limit
        if (i + 1) % API_GMAIL_LIMIT == 0:
            print('Waiting for a while...')
            time.sleep(EMAIL_WAIT_TIME)


def main():
    load_credentials()

    # Your email credentials and server settings
    from_email = os.environ['GOOGLE_ACCOUNT']
    # Get authenticated Gmail service
    gmail_service = get_gmail_service(os.environ['GOOGLE_CREDENTIALS_PATH'], os.environ['GOOGLE_REFRESH_TOKEN_PATH'])

    ac2gs_path = os.path.join(CACHE_DIR, 'ac2gs.json')
    ac_info_path = os.path.join(CACHE_DIR, 'ac_info.json')
    sac2gs_path = os.path.join(CACHE_DIR, 'sac2gs.json')
    sac_info_path = os.path.join(CACHE_DIR, 'sac_info.json')

    assert os.path.exists(ac2gs_path), 'ac2gs.json file does not exist'
    assert os.path.exists(ac_info_path), 'ac_info.json file does not exist'
    assert os.path.exists(sac2gs_path), 'sac2gs.json file does not exist'
    assert os.path.exists(sac_info_path), 'sac_info.json file does not exist'

    with open(ac2gs_path, 'r') as f:
        ac2gs = json.load(f)
    with open(ac_info_path, 'r') as f:
        ac_info = json.load(f)
    with open(sac2gs_path, 'r') as f:
        sac2gs = json.load(f)
    with open(sac_info_path, 'r') as f:
        sac_info = json.load(f)

    # NOTE: Replace with your conference name
    conference_name = "Conference"
    ac_subject = f"{conference_name} Review Tracking Spreadsheet Access"
    sac_subject = f"{conference_name} Review Tracking Spreadsheet Access"

    email_notify(gmail_service, from_email, ac2gs, ac_info, ac_subject)
    email_notify(gmail_service, from_email, sac2gs, sac_info, sac_subject)


if __name__ == '__main__':
    main()

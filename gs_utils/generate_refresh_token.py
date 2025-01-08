import os
from google_auth_oauthlib.flow import InstalledAppFlow
from src.utils import load_credentials


def get_credentials():
    # Define the scopes for the Google API
    load_credentials()
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive', 
        'https://www.googleapis.com/auth/gmail.send',
    ]

    flow = InstalledAppFlow.from_client_secrets_file(os.environ['GOOGLE_CREDENTIALS_PATH'], scopes)
    credentials = flow.run_local_server(port=0)
    return credentials


if __name__ == '__main__':
    creds = get_credentials()
    print("Access Token:", creds.token)
    print("Refresh Token:", creds.refresh_token)
    with open(os.environ['GOOGLE_REFRESH_TOKEN_PATH'], 'w') as f:
        f.write(creds.refresh_token)

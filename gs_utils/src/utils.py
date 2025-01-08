import os
import re
import json
import dotenv
import openreview
import gspread
import backoff
import logging
import logging.config
import base64
from email.mime.text import MIMEText
from gspread.exceptions import APIError
from gspread_formatting import (
    CellFormat,
    format_cell_range,
    ConditionalFormatRule,
    GridRange,
    BooleanRule,
    BooleanCondition,
    Color,
    get_conditional_format_rules
)
from src.constants import (
    ROWS,
    COLS,
    FACTOR,
    MAX_VALUE,
    MAX_TIME,
    MAX_TRIES,
)
# from oauth2client.service_account import ServiceAccountCredentials
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# ----- backoff logging utils -----
# Load logging configuration
logging.config.fileConfig('logs/logging.conf')

# Access logger
logger = logging.getLogger(__name__)


def log_backoff(details):
    """Log each backoff retry attempt."""
    logger.warning(f"Backing off {details['wait']:.1f} seconds after {details['tries']} tries "
                    f"calling function {details['target'].__name__} with args {details['args']} and kwargs {details['kwargs']}.")


def log_giveup(details):
    """Log final failure after exhausting all retries."""
    logger.error(f"Giving up after {details['tries']} tries calling function {details['target'].__name__} "
                  f"with args {details['args']} and kwargs {details['kwargs']}.")


# ----- Authentication utils -----
# Load the OpenReview credentials from the .env file
def load_credentials():
    dotenv.load_dotenv()


# ----- OpenReview general utils -----
# Get the OpenReview client
def get_client():
    client = openreview.api.OpenReviewClient(
        baseurl='https://api2.openreview.net',
        username=os.environ['OPENREVIEW_USERNAME'],
        password=os.environ['OPENREVIEW_PASSWORD'],
    )
    return client


# Get the OpenReview venue group for a given venue ID
def get_venue_grp(client, venue_id):
    venue_grp = client.get_group(venue_id)
    return venue_grp


# ----- OpenReview review utils -----
# Given a review content, return the number of words in the review
def words_count(review_content):
    length = 0
    for text in review_content.values():
        if 'value' not in text:
            continue
        text_value = text['value']
        if isinstance(text_value, str):
            length += len(re.findall(r'\b\w+\b', text_value))
    return length


# Obtain all paper submissions for the venue
def get_submissions(client, venue_id, venue_grp):
    submission_name = venue_grp.content['submission_name']['value']
    submissions = client.get_all_notes(invitation=f'{venue_id}/-/{submission_name}', details='replies')
    return submissions


# Process the submissions into a desired format for fetching wordcount information
def process_submissions(submissions, venue_grp, venue_id):
    submission_name = venue_grp.content['submission_name']['value']
    review_name = venue_grp.content['review_name']['value']
    reviewers_anon_name = venue_grp.content['reviewers_anon_name']['value']

    rtn = {}
    for submission in submissions:
        submission_dict = {}
        # Basic paper info
        submission_dict['forum_id'] = submission.id
        submission_dict['submission_number'] = submission.number
        submission_dict['title'] = submission.content['title']

        # Paper review
        reviews = {}
        for reply in submission.details['replies']:
            # Only show reviewers, not other types of replies
            if f'{venue_id}/{submission_name}{submission.number}/-/{review_name}' in reply['invitations']:
                # The key is the reviewer ID, and the value is the review content
                reviewer_id = reply['writers'][-1].split('/')[-1]
                assert reviewer_id.startswith(reviewers_anon_name), f"Unexpected reviewer ID: {reviewer_id}"
                reviews[reviewer_id] = reply['content']
        submission_dict['reviews'] = reviews

        rtn[submission.id] = submission_dict
    return rtn


# ----- OpenReview User info utils -----
def get_user_info(client, members):
    profiles = openreview.tools.get_profiles(client, members)
    rtn = {}
    for profile in profiles:
        profile_dict = {}
        profile_dict['id'] = profile.id
        profile_dict['name'] = profile.content['names'][0]['fullname']
        if 'preferredEmail' in profile.content:
            profile_dict['email'] = profile.content['preferredEmail']
        else:
            # There may be some guys who do not have a preferred email, use the last email as a backup
            profile_dict['email'] = profile.content['emails'][-1]

        rtn[profile.id] = profile_dict
    return rtn


# -----Global-progress-related utils -----
def calculate_global_progress(progress_dict):
    current, total = 0, 0
    for item in progress_dict.values():
        current += item["current"]
        total += item["total"]
    return {"current": current, "total": total}


# Function to format progress
def format_progress(current, total):
    # If total is 0, return N/A
    if total == 0:
        return "N/A"
    percentage = round(100 * current / total, 2)
    return f"{current}/{total} = ({percentage}%)"


# ----- Google Sheets utils -----
# NOTE: This is one of the most important function
# backoff helper on tons of 500 503 APIError (gspread), HttpError (googleapiclient), TimeoutError
@backoff.on_exception(backoff.expo, exception=(APIError, HttpError, TimeoutError), factor=FACTOR,
                      max_value=MAX_VALUE, max_tries=MAX_TRIES, max_time=MAX_TIME, jitter=backoff.random_jitter,
                      on_backoff=log_backoff, on_giveup=log_giveup)
def exec_func_w_backoff(func, *args, **kwargs):
    """Execute a function with retry on APIError using backoff."""
    return func(*args, **kwargs)


# Set up the credentials
def authenticate_gspread(json_keyfile, refresh_token_path, build_service=False):
    # scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
    # credentials = ServiceAccountCredentials.from_json_keyfile_name(json_keyfile, scope)
    # client = gspread.authorize(credentials)
    # client = gspread.oauth(credentials_filename=json_keyfile)
    
    with open(json_keyfile, 'r') as f:
        json_key = json.load(f)

    with open(refresh_token_path, 'r') as f:
        refresh_token = f.read()

    # NOTE: scopes are included in the refresh token
    creds = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=json_key['installed']['client_id'],
        client_secret=json_key['installed']['client_secret']
    )
    client = gspread.authorize(creds)

    if build_service:
        service = build('sheets', 'v4', credentials=creds)
        return client, service

    return client


# Use exponential backoff to handle API errors
def create_spreadsheet(client, sheet_name, init='ac'):
    assert init in ['ac', 'sac']
    # Create a spreadsheet for the AC
    spreadsheet = exec_func_w_backoff(client.create, sheet_name)

    if init == 'ac':
        # Create the 1 worksheets we need
        exec_func_w_backoff(spreadsheet.add_worksheet, title="Word Count", rows=ROWS, cols=COLS)
        exec_func_w_backoff(spreadsheet.add_worksheet, title="Rating", rows=ROWS, cols=COLS)
        # exec_func_w_backoff(spreadsheet.add_worksheet, title="Reviewer Info", rows=ROWS, cols=COLS)

        # Remove the default worksheet
        default_worksheet = exec_func_w_backoff(spreadsheet.get_worksheet, 0)
        exec_func_w_backoff(spreadsheet.del_worksheet, default_worksheet)

    elif init != 'sac':
        # For SACs, we just create a new worksheet
        raise ValueError(f"Unexpected init value: {init}")

    # spreadsheet.share(os.environ['GOOGLE_ACCOUNT'], perm_type='user', role='writer', notify=False)
    return spreadsheet


# Open the spreadsheet, also create it if it does not exist
# Use exponential backoff to handle API errors
def open_spreadsheet(client, sheet_url):
    spreadsheet = exec_func_w_backoff(client.open_by_url, sheet_url)
    return spreadsheet


def bold_range(worksheet, range_string):
    # Bold the range
    fmt = CellFormat(textFormat={'bold': True})
    exec_func_w_backoff(format_cell_range, worksheet, range_string, fmt)


def bold_column_names(worksheet):
    # Bold the first row
    bold_range(worksheet, '1:1')


def apply_conditional_coloring(worksheet, range_string):
    # Get existing conditional formatting rules
    curr_rules = exec_func_w_backoff(get_conditional_format_rules, worksheet)
    curr_rules.clear()

    # Define the formatting rules
    # NOTE: Modify here for your rules
    rules = [
        ConditionalFormatRule(
            ranges=[GridRange.from_a1_range(range_string, worksheet)],
            booleanRule=BooleanRule(
                condition=BooleanCondition('CUSTOM_FORMULA',
                                           [f'=AND(ISNUMBER({range_string}), {range_string} > 0, {range_string} < 200)']),
                format=CellFormat(backgroundColor=Color(1, 0.9, 0.9))  # Light red
            )
        ),
        ConditionalFormatRule(
            ranges=[GridRange.from_a1_range(range_string, worksheet)],
            booleanRule=BooleanRule(
                condition=BooleanCondition('CUSTOM_FORMULA',
                                           [f'=AND(ISNUMBER({range_string}), {range_string} >= 200, {range_string} <= 300)']),
                format=CellFormat(backgroundColor=Color(1, 1, 0.8))  # Light yellow
            )
        ),
        ConditionalFormatRule(
            ranges=[GridRange.from_a1_range(range_string, worksheet)],
            booleanRule=BooleanRule(
                condition=BooleanCondition('CUSTOM_FORMULA', 
                                           [f'=AND(ISNUMBER({range_string}), {range_string} > 300)']),
                format=CellFormat(backgroundColor=Color(0.8, 1, 0.8))  # Light green
            )
        )
    ]
    
    curr_rules.extend(rules)
    exec_func_w_backoff(curr_rules.save)


def split_range(range_str):
    """
    Splits a cell range string into its respective start and end columns and rows.

    Parameters:
    range_str (str): A string representing a range in the format 'A1:AX100'.

    Returns:
    tuple: A tuple containing (start_column, start_row, end_column, end_row) if valid, else None.
    """
    # Regular expression to match column letters and row numbers
    pattern = r"([A-Z]+)(\d+):([A-Z]+)(\d+)"
    
    # Search the pattern in the range string
    match = re.search(pattern, range_str)
    
    if match:
        start_column = match.group(1)
        start_row = match.group(2)
        end_column = match.group(3)
        end_row = match.group(4)
        
        return (start_column, start_row, end_column, end_row)
    else:
        print("No match found. Please check the range string format.")
        return None


# ----- Google Sheets copying utils -----
# Useful for SACs that have been assigned to multiple ACs
def get_sheet_id_by_title(service, spreadsheet_id, sheet_title):
    """
    Get the sheet ID of a worksheet by its title.

    Parameters:
        spreadsheet_id (str): The ID of the spreadsheet.
        sheet_title (str): The title of the worksheet.

    Returns:
        int: The ID of the worksheet.
    """
    request = service.spreadsheets().get(spreadsheetId=spreadsheet_id)
    spreadsheet = exec_func_w_backoff(request.execute)
    sheets = spreadsheet.get('sheets', [])

    for sheet in sheets:
        if sheet['properties']['title'] == sheet_title:
            return sheet['properties']['sheetId']
    raise ValueError(f'Sheet with title "{sheet_title}" not found.')


# Remove all cell colour
def remove_all_colors(spreadsheet, worksheet):
    """
    Remove all color formatting from a Google Sheet.

    Args:
        spreadsheet (gspread.models.Spreadsheet): The spreadsheet object.
        worksheet (gspread.models.Worksheet): The worksheet object.
    """
    # Get the number of rows and columns in the worksheet
    row_count = worksheet.row_count
    col_count = worksheet.col_count

    # Construct the batch update request to remove all background colors
    request = {
        "repeatCell": {
            "range": {
                "sheetId": worksheet.id,
                "startRowIndex": 0,
                "endRowIndex": row_count,
                "startColumnIndex": 0,
                "endColumnIndex": col_count
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": {
                        "red": 1, "green": 1, "blue": 1, "alpha": 0
                    }
                }
            },
            "fields": "userEnteredFormat.backgroundColor"
        }
    }

    # Send the request to the Google Sheets API
    exec_func_w_backoff(spreadsheet.batch_update, {"requests": [request]})


# Remove all boarder formatting
def remove_all_borders(spreadsheet, worksheet):
    """
    Remove all right border formatting from a Google Sheet.

    Args:
        spreadsheet (gspread.models.Spreadsheet): The spreadsheet object.
        worksheet (gspread.models.Worksheet): The worksheet object.
    """
    # Get the number of rows and columns in the worksheet
    row_count = worksheet.row_count
    col_count = worksheet.col_count

    # Construct the batch update request to remove all right borders
    requests = []
    for col_index in range(col_count):
        request = {
            "updateBorders": {
                "range": {
                    "sheetId": worksheet.id,
                    "startRowIndex": 0,
                    "endRowIndex": row_count,
                    "startColumnIndex": col_index,
                    "endColumnIndex": col_index + 1
                },
                "top": {
                    "style": "NONE"
                },
                "bottom": {
                    "style": "NONE"
                },
                "left": {
                    "style": "NONE"
                },
                "right": {
                    "style": "NONE"
                },
                "innerHorizontal": {
                    "style": "NONE"
                },
                "innerVertical": {
                    "style": "NONE"
                }
            }
        }
        requests.append(request)

    # Send the request to the Google Sheets API
    exec_func_w_backoff(spreadsheet.batch_update, {"requests": requests})


# Add color formatting to specified columns
def add_col_colors(spreadsheet, worksheet, effective_rows, col_numbers, color):
    """
    Add color formatting to specified columns in a Google Sheet.

    Args:
        spreadsheet (gspread.models.Spreadsheet): The spreadsheet object.
        worksheet (gspread.models.Worksheet): The worksheet object.
        effective_rows (int): The number of rows to apply the color formatting to.
        col_numbers (list): A list of column indices (0-based) to apply the color formatting.
        color (dict): The color to apply in the format {'red': float, 'green': float, 'blue': float, 'alpha': float}.
    """
    # Construct the batch update request to add color formatting
    requests = []
    for col_index in col_numbers:
        request = {
            "repeatCell": {
                "range": {
                    "sheetId": worksheet.id,
                    "startRowIndex": 0,
                    "endRowIndex": effective_rows,
                    "startColumnIndex": col_index,
                    "endColumnIndex": col_index + 1
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": color
                    }
                },
                "fields": "userEnteredFormat.backgroundColor"
            }
        }
        requests.append(request)

    # Send the request to the Google Sheets API
    exec_func_w_backoff(spreadsheet.batch_update, {"requests": requests})


def copy_worksheet(service, source_spreadsheet_id, source_sheet_id, target_spreadsheet_id):
    """
    Copy a worksheet from one spreadsheet to another using the Google Sheets API.

    Parameters:
        source_spreadsheet_id (str): The ID of the source spreadsheet.
        source_sheet_id (int): The sheet ID of the worksheet to be copied.
        target_spreadsheet_id (str): The ID of the target spreadsheet.

    Returns:
        dict: Response from the API call with details of the newly created worksheet.
    """
    request = service.spreadsheets().sheets().copyTo(
        spreadsheetId=source_spreadsheet_id,
        sheetId=source_sheet_id,
        body={'destinationSpreadsheetId': target_spreadsheet_id}
    )
    return exec_func_w_backoff(request.execute)


def rename_worksheet(service, spreadsheet_id, sheet_id, new_title):
    """
    Rename a worksheet in a spreadsheet using the Google Sheets API.

    Parameters:
        spreadsheet_id (str): The ID of the spreadsheet.
        sheet_id (int): The ID of the worksheet to be renamed.
        new_title (str): The new title for the worksheet.
    """
    request = service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            'requests': [
                {
                    'updateSheetProperties': {
                        'properties': {
                            'sheetId': sheet_id,
                            'title': new_title
                        },
                        'fields': 'title'
                    }
                }
            ]
        }
    )

    exec_func_w_backoff(request.execute)


# Function trying to open a worksheet in a spreadsheet, if not exist, create it, and put it in pos 0
def open_or_create_worksheet(spreadsheet, worksheet_name):
    try:
        # Try to open the worksheet by name
        worksheet = exec_func_w_backoff(spreadsheet.worksheet, worksheet_name)
    except gspread.exceptions.WorksheetNotFound:
        # If the worksheet does not exist, create it
        worksheet = exec_func_w_backoff(spreadsheet.add_worksheet, title=worksheet_name, rows=ROWS, cols=COLS)

    # Reorder the worksheets to place the worksheet at index 0
    worksheets = exec_func_w_backoff(spreadsheet.worksheets)
    worksheet_ids = [ws.id for ws in worksheets]

    # Find the index of the worksheet in the list
    target_index = worksheet_ids.index(worksheet.id)
    
    if target_index != 0:
        # Move the worksheet to the first position
        requests_msg = {
            "requests": [
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": worksheet.id,
                            "index": 0
                        },
                        "fields": "index"
                    }
                }
            ]
        }
        exec_func_w_backoff(spreadsheet.batch_update, requests_msg)

    return worksheet


def convert_column_to_text(spreadsheet, worksheet, column_index, start_row, end_row):
    request = {
            "repeatCell": {
                "range": {
                    "sheetId": worksheet.id,
                    "startRowIndex": start_row - 1,
                    "endRowIndex": end_row,
                    "startColumnIndex": column_index,
                    "endColumnIndex": column_index + 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "numberFormat": {
                            "type": "TEXT"
                        }
                    }
                },
                "fields": "userEnteredFormat.numberFormat"
            }
        }
    
    exec_func_w_backoff(spreadsheet.batch_update, {"requests": [request]})


def add_right_borders(spreadsheet, worksheet, effective_rows, col_numbers):
    # NOTE: end_idx is exclusive
    requests = []
    for col_index in col_numbers:
        request = {
            "updateBorders": {
                "range": {
                    "sheetId": worksheet.id,
                    "startRowIndex": 0,
                    "endRowIndex": effective_rows,
                    "startColumnIndex": col_index,
                    "endColumnIndex": col_index + 1
                },
                "right": {
                    "style": "SOLID",
                    "width": 1,
                    "color": {
                        "red": 0, "green": 0, "blue": 0, "alpha": 1
                    }
                }
            }
        }
        requests.append(request)

    # Send the request to the Google Sheets API
    exec_func_w_backoff(spreadsheet.batch_update, {"requests": requests})


# Function to check if a worksheet already exists in the target spreadsheet
def worksheet_exists(service, spreadsheet_id, sheet_title):
    """Check if a worksheet with the given title exists in the spreadsheet."""
    request = service.spreadsheets().get(spreadsheetId=spreadsheet_id)
    spreadsheet = exec_func_w_backoff(request.execute)
    sheets = spreadsheet.get('sheets', [])

    for sheet in sheets:
        if sheet['properties']['title'] == sheet_title:
            return sheet['properties']['sheetId']
    return None


def remove_sheets_starting_with(service, spreadsheet_id, prefix):
    """Remove all sheets starting with a given prefix in the specified spreadsheet."""
    spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheets = spreadsheet.get('sheets', [])
    
    # Find sheets that start with the specified prefix
    sheet_ids_to_remove = [sheet['properties']['sheetId'] for sheet in sheets if sheet['properties']['title'].startswith(prefix)]
    
    # Prepare batch update request to delete the sheets
    requests = [{'deleteSheet': {'sheetId': sheet_id}} for sheet_id in sheet_ids_to_remove]
    if requests:
        body = {'requests': requests}
        request = service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body)
        exec_func_w_backoff(request.execute)


# Function to delete a worksheet by ID
def delete_worksheet(service, spreadsheet_id, sheet_id):
    """Delete a worksheet by its sheet ID."""
    request = {
        'requests': [
            {
                'deleteSheet': {
                    'sheetId': sheet_id
                }
            }
        ]
    }

    exec_func_w_backoff(service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=request).execute)


# ----- Pandas utils -----
def drop_unnamed_columns(df):
    # Drop columns that have 'Unnamed' in the column header
    df = df.loc[:, ~df.columns.str.contains('^Unnamed')]
    return df


# ----- Google Drive remove files -----
def find_google_sheets_files(drive_service, filename=None):
    """
    List Google Sheets files and return their IDs if they match a given filename.

    Args:
        filename (str): The filename to filter the files by. If None, all Google Sheets files are returned.

    Returns:
        List[Dict]: A list of file information (ID and name).
    """
    query = "mimeType='application/vnd.google-apps.spreadsheet'"
    if filename:
        # Escaping the filename by wrapping it with double quotes and escaping quotes inside
        escaped_filename = filename.replace("'", "\\'")
        query += f" and name='{escaped_filename}'"

    results = exec_func_w_backoff(drive_service.files().list(
        q=query,
        fields="files(id, name)"
    ).execute)

    files = results.get('files', [])
    return files


def remove_google_sheets_files(drive_service, file_ids):
    """
    Delete Google Sheets files given their file IDs.

    Args:
        file_ids (List[str]): A list of file IDs to be deleted.
    """
    for file_id in file_ids:
        try:
            exec_func_w_backoff(drive_service.files().delete(fileId=file_id).execute)
            print(f"Deleted file with ID: {file_id}")
        except Exception as e:
            print(f"Failed to delete file with ID: {file_id}. Error: {e}")


# ----- Email notification utils -----
def get_gmail_service(json_keyfile, refresh_token_path):
    """Authenticate and return a Gmail service object."""
    with open(json_keyfile, 'r') as f:
        json_key = json.load(f)

    with open(refresh_token_path, 'r') as f:
        refresh_token = f.read()

    # NOTE: scopes are included in the refresh token
    creds = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=json_key['installed']['client_id'],
        client_secret=json_key['installed']['client_secret'],
        scopes=['https://www.googleapis.com/auth/gmail.send']
    )
    return build('gmail', 'v1', credentials=creds)


def send_email(service, from_email, to_email, subject, message):
    """Send an email using the Gmail API."""
    mime_message = MIMEText(message)
    mime_message['To'] = to_email
    mime_message['From'] = from_email
    mime_message['Subject'] = subject
    raw_message = base64.urlsafe_b64encode(mime_message.as_bytes()).decode()

    message_body = {
        'raw': raw_message
    }

    try:
        request = service.users().messages().send(userId='me', body=message_body)
        message = exec_func_w_backoff(request.execute)
        print(f'Message Id: {message["id"]}')
        print('Email sent successfully!')
    except Exception as error:
        print(f'An error occurred: {error}')

CACHE_DIR = ".cache"

# ----- Main script execution sleep config -----
# increase the duration if errors happen oftenly
SCRIPT_WAIT_PERIOD = 60

# ----- Google Sheet configs -----
# usually rows are number of submissions under an AC/SAC, so 100 should be enough
# 50 columns are the number of reviewers, so 50 should be enough
ROWS = 100
COLS = 50

# ------ Backoff configs -----
FACTOR = 10
MAX_VALUE = 60  # single expo backoff
MAX_TIME = 8 * 60  # max all backoff time
MAX_TRIES = 10

# ----- Email configs -----
EMAIL_TEMPLATE = """Dear {},

Please use the following link to access the review tracking spreadsheet.

{}

Please do not share this link with anyone else. Let us know if you have any questions.

Best regards,
ACM Multimedia 2024 Program Chairs
"""
API_GMAIL_LIMIT = 60
EMAIL_WAIT_TIME = 30

# ----- Google Sheet API configs -----
API_CREATE_LIMIT = 150
API_UPDATE_LIMIT = 15
API_SHARE_LIMIT = 70
WAIT_TIME = 45
SAC_API_SHEET_UPDATE_LIMIT = 10

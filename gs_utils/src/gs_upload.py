import os
import time
import json
import gspread.utils
import pandas as pd
import gspread
import tqdm
from gspread_formatting import set_column_width
from gspread_dataframe import get_as_dataframe, set_with_dataframe
from src.constants import API_CREATE_LIMIT, API_UPDATE_LIMIT, WAIT_TIME, CACHE_DIR, SAC_API_SHEET_UPDATE_LIMIT
from src.utils import (
    format_progress,
    drop_unnamed_columns,
    create_spreadsheet,
    open_spreadsheet,
    bold_column_names,
    bold_range,
    apply_conditional_coloring,
    split_range,
    open_or_create_worksheet,
    exec_func_w_backoff,
    remove_all_borders,
    remove_all_colors,
    add_col_colors,
    add_right_borders,
    get_sheet_id_by_title,
    worksheet_exists,
    rename_worksheet,
    remove_sheets_starting_with,
    delete_worksheet,
    copy_worksheet,
)


# Set the option to handle downcasting explicitly
pd.set_option('future.no_silent_downcasting', True)


def gs_ac_upload(client):
    # NOTE: The `client` variable refers to a Google Sheets client, not an OpenReview client
    cache_path = CACHE_DIR
    data_path = os.path.join(cache_path, 'data')
    word_count_path = os.path.join(data_path, 'word_count')
    rating_path = os.path.join(data_path, 'rating')
    # reviewerinfo_path = os.path.join(data_path, 'reviewer_info')
    paper_progress_path = os.path.join(data_path, 'paper_progress')
    review_progress_path = os.path.join(data_path, 'review_progress')
    global_progress_path = os.path.join(data_path, 'global_progress')
    ac2gs_path = os.path.join(cache_path, 'ac2gs.json')

    # Get the maximum assigned submissions
    ac2id_path = os.path.join(cache_path, 'assign_ac2id.json')
    with open(ac2id_path, 'r') as f:
        ac2id = json.load(f)
    max_assigned = max([len(ids) for ac, ids in ac2id.items() if ac != 'Not assigned'])
    # There are 2 additional rows between the word count and the progress rows
    # 4 = 2 (additional rows) + 1 (zero-indexed) + 1 (header row)
    progress_row = max_assigned + 4

    # Get all filenames
    all_filenames = os.listdir(word_count_path)

    # Create a file for each AC
    if not os.path.exists(ac2gs_path):
        ac2gs = {}

        for i, file in enumerate(all_filenames):
            # Skip AC's with empty word count files (there was one...)
            if pd.read_csv(os.path.join(word_count_path, file)).empty:
                continue

            ac_name = os.path.splitext(file)[0]
            spreadsheet = create_spreadsheet(client, ac_name, init='ac')
            ac2gs[ac_name] = spreadsheet.url

            # Avoid API limit
            if (i + 1) % API_CREATE_LIMIT == 0:
                time.sleep(WAIT_TIME)
        
        # Avoid API limit after creating all spreadsheets
        time.sleep(WAIT_TIME)

        # Save the ac2gs mapping
        with open(ac2gs_path, 'w') as f:
            json.dump(ac2gs, f)

    # If the corresponding file exists, load it
    else:
        with open(ac2gs_path, 'r') as f:
            ac2gs = json.load(f)

    # Load the global progress information
    with open(os.path.join(global_progress_path, 'paper_global_progress.json'), 'r') as f:
        paper_global_progress = json.load(f)
    
    with open(os.path.join(global_progress_path, 'review_global_progress.json'), 'r') as f:
        review_global_progress = json.load(f)
    
    ac2gs_modified_flag = False

    # Iterate through the spreadsheet for each AC
    for i, file in enumerate(tqdm.tqdm(all_filenames)):
        # Get the word count dataframes, helps us to do the condition check on whether
        # real information is included in the spreadsheet and decide whether to upload
        # ------ Stage 1: word count + progress sheet ------
        local_df = pd.read_csv(os.path.join(word_count_path, file))

        # If no data is present, skip the upload
        if local_df.empty:
            continue

        ac_name = os.path.splitext(file)[0]
        if ac_name in ac2gs:
            spreadsheet = open_spreadsheet(client, ac2gs[ac_name])
        else:
            print(f"Creating a new spreadsheet for {ac_name}")
            spreadsheet = create_spreadsheet(client, ac_name, init='ac')
            ac2gs[ac_name] = spreadsheet.url
            ac2gs_modified_flag = True

        # --- Sheet 1: Word count ---
        # NOTE: Sometimes the spreadsheet may be created from other sources, so we need to open/create
        worksheet = open_or_create_worksheet(spreadsheet, "Word Count")

        # Progress, we force overwrite for the progress contents ---
        # Load the AC's progress1
        with open(os.path.join(paper_progress_path, f'{ac_name}.json'), 'r') as f:
            paper_progress = json.load(f)
        with open(os.path.join(review_progress_path, f'{ac_name}.json'), 'r') as f:
            review_progress = json.load(f)

        # Construct the local dataframe
        progress_df = pd.DataFrame({
            'Review Progress (Your batch)': [format_progress(review_progress['current'], review_progress['total'])],
            'Review Progress (Global)': [format_progress(review_global_progress['current'], review_global_progress['total'])],
            'Paper Progress (Your batch)': [format_progress(paper_progress['current'], paper_progress['total'])],
            'Paper Progress (Global)': [format_progress(paper_global_progress['current'], paper_global_progress['total'])],
        })

        # Get the word count ranges in the spreadsheet
        # NOTE 1: DataFrame is one row less than the actual sheet (headers!)
        # NOTE 2: DataFrame rows & cols are one-indexed
        reviewer_columns = [col for col in local_df.columns if col.startswith('Reviewer ')]
        reviewer_col_idx = [local_df.columns.get_loc(col) for col in reviewer_columns]

        row_start, col_start = 0, min(reviewer_col_idx)
        row_end, col_end = local_df.shape[0] - 1, max(reviewer_col_idx)

        topleft = gspread.utils.rowcol_to_a1(row_start + 2, col_start + 1)
        bottomright = gspread.utils.rowcol_to_a1(row_end + 2, col_end + 1)

        word_count_range = f'{topleft}:{bottomright}'

        # Get the remote df and drop all rows where all elements are NaN
        remote_df = drop_unnamed_columns(exec_func_w_backoff(get_as_dataframe, worksheet).dropna(how="all"))

        # If the remote dataframe is not empty, we need to copy the "Action?" column
        if not remote_df.empty:
            merge_df = local_df.merge(remote_df, on='Submission Number', how='left', suffixes=('', '_remote'))
            merge_df['Action?'] = merge_df['Action?_remote'].fillna(local_df['Action?'])
            local_df['Action?'] = merge_df['Action?']

            # Clean the current sheet, maybe expensive, but robust to deletion of rows
            exec_func_w_backoff(worksheet.clear)

        # If the remote dataframe is empty, we do some formatting
        else:
            # Get the total number of rows and columns in the worksheet
            total_rows = worksheet.row_count
            total_columns = worksheet.col_count
            range_str = f'{gspread.utils.rowcol_to_a1(1, 1)}:{gspread.utils.rowcol_to_a1(total_rows, total_columns)}'
            col_start_str, _, col_end_str, _ = split_range(range_str)

            # Formatting the worksheet (GLOBAL config)
            # Bold column names (GLOBAL)
            bold_column_names(worksheet)

            # Bold progress column names (GLOBAL)
            progress_col_range_str = (
                f'{gspread.utils.rowcol_to_a1(progress_row, 1)}:'
                f'{gspread.utils.rowcol_to_a1(progress_row, len(progress_df.columns))}'
            )
            bold_range(worksheet, progress_col_range_str)

            # Resize the columns (GLOBAL)
            exec_func_w_backoff(set_column_width, worksheet, f"{col_start_str}:{col_end_str}", 105)

            # Set cells to wrap text (GLOBAL)
            exec_func_w_backoff(worksheet.format, range_str, {"wrapStrategy": "WRAP"})

            # Auto adjust row heights (GLOBAL)
            exec_func_w_backoff(worksheet.rows_auto_resize, 0, total_rows)

        # Set the local dataframe to the worksheet, force update
        exec_func_w_backoff(set_with_dataframe, worksheet, local_df, row=1, col=1)

        # Refresh conditional formatting ranges, as the papers might have changed
        apply_conditional_coloring(worksheet, word_count_range)

        # Force overwrite the progress sheet with the latest progress
        exec_func_w_backoff(set_with_dataframe, worksheet, progress_df, row=progress_row, col=1)

        # ----- Sheet 2: ratings -----
        # We update things to the rating spreadsheet
        local_df = pd.read_csv(os.path.join(rating_path, file))

        # Skip if the local dataframe is empty
        if local_df.empty:
            continue

        # This will try to open the Rating worksheet, if it does not exist, it will create it
        worksheet = open_or_create_worksheet(spreadsheet, "Rating")
        remote_df = drop_unnamed_columns(exec_func_w_backoff(get_as_dataframe, worksheet).dropna(how="all"))

        # Whether we need to reset the boarder and color formatting
        reset_format = False

        if not remote_df.empty:
            exec_func_w_backoff(worksheet.clear)

            # If there are any changes in the columns, or number of submissions, we reset the formatting
            if (local_df.columns != remote_df.columns).any() or (local_df.shape[0] != remote_df.shape[0]):
                reset_format = True

        # If the remote dataframe is empty, we do some formatting
        else:
            # Get the total number of rows and columns in the worksheet, this is for GLOBAL formatting
            total_rows = worksheet.row_count
            total_columns = worksheet.col_count
            range_str = f'{gspread.utils.rowcol_to_a1(1, 1)}:{gspread.utils.rowcol_to_a1(total_rows, total_columns)}'
            col_start_str, _, col_end_str, _ = split_range(range_str)

            # Formatting the worksheet (GLOBAL config)
            # Bold column names (GLOBAL)
            bold_column_names(worksheet)

            # Resize the columns (GLOBAL)
            exec_func_w_backoff(set_column_width, worksheet, f"{col_start_str}:{col_end_str}", 80)

            # Set cells to wrap text (GLOBAL)
            exec_func_w_backoff(worksheet.format, range_str, {"wrapStrategy": "WRAP"})

            # Auto adjust row heights (GLOBAL)
            exec_func_w_backoff(worksheet.rows_auto_resize, 0, total_rows)

            # Since we have just created the worksheet, we need to reset the formatting
            reset_format = True

        # Set the local dataframe to the worksheet, force update
        exec_func_w_backoff(set_with_dataframe, worksheet, local_df, row=1, col=1)

        if reset_format:
            # Remove all borders and colours
            remove_all_colors(spreadsheet, worksheet)
            remove_all_borders(spreadsheet, worksheet)
            # Apply formatting ... (e.g., vertical lines, colors)
            # + 1 for the extra column names row, calculate how high the boarders should be
            effective_rows = local_df.shape[0] + 1
            # Filter columns that do not contain 'Rtng', calculate which columns to apply the boarders
            filtered_columns = [col for col in local_df.columns if 'Rtng' not in col]
            last_non_rtng_index = local_df.columns.get_loc(filtered_columns[-1]) if filtered_columns else -1
            col_numbers = list(range(last_non_rtng_index, local_df.shape[-1], 2))
            # Apply the right borders
            add_right_borders(spreadsheet, worksheet, effective_rows, col_numbers)
            # Add colors to final rating columns
            # Define the color (e.g., light blue)
            color1 = {
                'red': 0.85,
                'green': 0.95,
                'blue': 1.0,
                'alpha': 1
            }
            color2 = {
                'red': 1.0,
                'green': 1.0,
                'blue': 0.8,
                'alpha': 1
            }
            cols_grp_1, cols_grp_2 = [], []
            for i, elem in enumerate(range(last_non_rtng_index + 1, local_df.shape[1], 2)):
                if i % 2 == 0:
                    cols_grp_1.append(elem)
                    cols_grp_1.append(elem + 1)
                else:
                    cols_grp_2.append(elem)
                    cols_grp_2.append(elem + 1)
            # Add color
            add_col_colors(spreadsheet, worksheet, effective_rows, cols_grp_1, color1)
            add_col_colors(spreadsheet, worksheet, effective_rows, cols_grp_2, color2)

        # NOTE: For privacy reasons, we do not upload the reviewer info sheet, if your want, uncomment the code below
        # NOTE: You might have to tweek the code in utils, to create a new worksheet named 'Reviewer Info' to support this
        # --- Sheet 3: Reviewer info ---
        # NOTE: This shouldn't be updated once created, since reviewers are fixed
        # worksheet = spreadsheet.worksheet('Reviewer Info')

        # # Get the remote df and drop all rows where all elements are NaN
        # remote_df = drop_unnamed_columns(get_as_dataframe(worksheet).dropna(how="all"))

        # # If the remote dataframe is empty, directly set the local dataframe
        # # Otherwise, we don't even need to load/update the reviewer info
        # if remote_df.empty:
        #     # Get the local dataframe
        #     local_df = pd.read_csv(os.path.join(reviewerinfo_path, file))
        #     set_with_dataframe(worksheet, local_df)

        #     # Formatting: Bold column names, larger column width, etc.
        #     bold_column_names(worksheet)
        #     col_range_str = f'{gspread.utils.rowcol_to_a1(1, 1)[0]}:{gspread.utils.rowcol_to_a1(1, len(local_df.columns))[0]}'
        #     set_column_width(worksheet, col_range_str, 150)

        # Avoid API limit
        if (i + 1) % API_UPDATE_LIMIT == 0:
            time.sleep(WAIT_TIME)
    
    # Save the ac2gs mapping if modified
    if ac2gs_modified_flag:
        with open(ac2gs_path, 'w') as f:
            json.dump(ac2gs, f)


def gs_sac_upload(client, service):
    cache_path = CACHE_DIR
    ac2gs_path = os.path.join(cache_path, 'ac2gs.json')
    sac2gs_path = os.path.join(cache_path, 'sac2gs.json')
    assign_sac2ac_path = os.path.join(cache_path, 'assign_sac2ac.json')

    assert os.path.exists(ac2gs_path), f"File not found: {ac2gs_path}"
    assert os.path.exists(assign_sac2ac_path), f"File not found: {assign_sac2ac_path}"

    with open(ac2gs_path, 'r') as f:
        ac2gs = json.load(f)
    with open(assign_sac2ac_path, 'r') as f:
        assign_sac2ac = json.load(f)

    if not os.path.exists(sac2gs_path):
        sac2gs = {}
        for i, (sac, ac_ids) in enumerate(assign_sac2ac.items()):
            # Skip SACs that have not been assigned
            if sac == 'Not assigned':
                continue
            
            # Only care about SACs that have been assigned, create spreadsheet for them
            spreadsheet = create_spreadsheet(client, sac, init='sac')
            sac2gs[sac] = spreadsheet.url

            # API limit reached, wait for a while
            if (i + 1) % API_CREATE_LIMIT == 0:
                time.sleep(WAIT_TIME)

        time.sleep(WAIT_TIME)

        with open(sac2gs_path, 'w') as f:
            json.dump(sac2gs, f)

    else:
        with open(sac2gs_path, 'r') as f:
            sac2gs = json.load(f)

    for sac_id, ac_ids in tqdm.tqdm(assign_sac2ac.items()):
        # Skip SACs that have not been assigned
        # Skip SACs that have not been assigned to any AC
        if sac_id == 'Not assigned' or not ac_ids:
            continue

        # Load the spreadsheet for the SAC
        tgt_spreadsheet = open_spreadsheet(client, sac2gs[sac_id])
        tgt_spreadsheet_id = tgt_spreadsheet.id

        # Copy each AC's specified worksheet to the target spreadsheet
        sheet_names = ["Word Count", "Rating"]
        for i, ac_id in enumerate(ac_ids):
            for j, sheet_name in enumerate(sheet_names):
                # There may be one AC that does not have any paper - no GoogleSheet
                if ac_id not in ac2gs:
                    continue

                # Identify a single sheet with AC's ID and the sheet name
                tgt_sheet_name = f"{ac_id} - {sheet_name}"

                # Get the source spreadsheet ID
                src_spreadsheet = open_spreadsheet(client, ac2gs[ac_id])
                src_spreadsheet_id = src_spreadsheet.id

                # Get the sheet ID of specified worksheet in the source spreadsheet
                src_sheet_id = get_sheet_id_by_title(service, src_spreadsheet_id, sheet_name)

                # Check if a worksheet with the same name already exists in the target spreadsheet
                tgt_sheet_id = worksheet_exists(service, tgt_spreadsheet_id, tgt_sheet_name)
                if tgt_sheet_id:
                    # If the worksheet already exists, delete it
                    delete_worksheet(service, tgt_spreadsheet_id, tgt_sheet_id)

                # Copy the specified worksheet to the target spreadsheet
                copied_sheet = copy_worksheet(service, src_spreadsheet_id, src_sheet_id, tgt_spreadsheet_id)

                # Rename the copied worksheet in the target spreadsheet to the corresponding AC ID + sheet name
                rename_worksheet(service, tgt_spreadsheet_id, copied_sheet['sheetId'], tgt_sheet_name)

                if (i * len(sheet_names) + j + 1) % SAC_API_SHEET_UPDATE_LIMIT == 0:
                    time.sleep(WAIT_TIME)

        # We need to delete the default worksheets, name starts with "Sheet"
        remove_sheets_starting_with(service, tgt_spreadsheet_id, 'Sheet')

        # Remove all spread sheet startswith "Copy of" in the name after tackling with each worksheet
        # NOTE: Copy & Rename may fail, and leave an intermediate sheet with "Copy of" in the name, do a cleanup here
        remove_sheets_starting_with(service, tgt_spreadsheet_id, 'Copy of')

        # API limit may have reached, wait for a SHORTER while before we take the next SAC
        time.sleep(WAIT_TIME // 2)

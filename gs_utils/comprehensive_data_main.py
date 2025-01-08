"""
This script is designed for PCs to gain a comprehensive overview of conference data after final decisions have been made for each paper.

The script generates two output files in .cache/data/:

1. `valid_paper_all_details.xlsx`: Contains detailed information about submissions with at least one review. The details include: the following columns:
    - submission_number, title, primary_area, decision, is_withdraw
    - comment_word_count, review_word_counts, suitability, confidence
    - init_ratings, final_ratings, raw_final_ratings
    - meta_review_word_counts, meta_review_decision, meta_review_confidence
2. `review_word_counts_over_time.xlsx`: Provides trends of review word counts over time, organized by submission and day. This data helps analyze whether reviews submitted closer to the deadline tend to be shorter or longer compared to those submitted earlier.
"""

import os
from functools import partial
from datetime import datetime, timedelta
import multiprocessing as mp
import openreview
import pandas as pd
from tqdm import tqdm
from rich import print
import pandas as pd
from src.utils import (
    load_credentials,
    get_client,
)
from src.constants import CACHE_DIR


# Helper functions that will be used later
def convert_time(timestamp_ms):
    timestamp_s = timestamp_ms / 1000
    date_time = datetime.fromtimestamp(timestamp_s)
    return date_time.strftime("%Y-%m-%d")


def get_word_count(content_dict):
    word_count = 0
    for k, v in content_dict.items():
        if 'value' in v and type(v['value']) == str:
            word_count += len(v['value'].split())
    return word_count


def process_review(client, review):
    # get id
    signature = review.signatures[0]
    sub_num, rev_id = signature.split('/')[-2:]
    sub_num = sub_num.split('Submission')[-1]
    rev_id = rev_id.split('Reviewer_')[-1]
    row_id = tuple([sub_num, rev_id])
    
    # get all edits
    edits = client.get_note_edits(review.id)
    edits = [elem for elem in edits if signature in elem.signatures]
    edits = sorted(edits, key=lambda x: x.cdate, reverse=False)

    content_dict = {}
    date2wordcount = {}
    for edit in edits:
        # print(edit['note'].content)
        content_dict.update(edit.note.content)
        date = convert_time(edit.cdate)
        word_count = get_word_count(content_dict)
        date2wordcount[date] = word_count
    
    return {row_id: date2wordcount}


def main():
    load_credentials()
    client = get_client()

    # Define the conference ID and the accepted papers invitation ID
    venue_id = os.environ['OPENREVIEW_VENUE_ID']
    venue_group = client.get_group(venue_id)
    submission_name = venue_group.content['submission_name']['value']
    submissions = client.get_all_notes(invitation=f'{venue_id}/-/{submission_name}', details='replies')

    outputs = []
    for s in tqdm(submissions):
    # for s in tqdm(submissions[:1]):  # dbg
        # author_attrs
        is_withdrawn = False
        primary_area = s.content['primary_subject_area']['value']
        primary_area = primary_area.split('[')[-1].split(']')[0]

        # pc_attrs
        decision = None

        # rvw_attrs
        comment_word_count = []
        word_counts = []
        suitability = []
        confidence = []
        init_ratings = []
        final_ratings = []
        raw_final_ratings = []

        # ac_attrs
        meta_word_counts = []
        meta_decision = []
        meta_confidence = []

        for reply in s.details['replies']:
            signature = reply['signatures'][0].split("/")[-1]
            if signature.startswith("Program_Chairs"):
                if 'decision' in reply['content']:
                    assert decision is None
                    decision = reply['content']['decision']['value']

            elif signature.startswith("Reviewer_"):
                is_review = f'{venue_id}/Submission{s.number}/-/Official_Review' in reply['invitations']
                if is_review:
                    # Officisla reviews - just reviews...
                    word_count = 0
                    for k, v in reply['content'].items():
                        if 'value' in v and type(v['value']) == str:
                            word_count += len(v['value'].split())
                    word_counts.append(word_count)

                    if 'suitability' in reply['content']:
                        suitability.append(reply['content']['suitability']['value'])
                    else:
                        suitability.append(4)  # <-- let's give them a decent score here...
                    init_ratings.append(reply['content']['rating']['value'])
                    if 'final_rating' in reply['content'] and 'value' in reply['content']['final_rating']:
                        final_ratings.append(reply['content']['final_rating']['value'])
                        raw_final_ratings.append(reply['content']['final_rating']['value'])
                    else:
                        final_ratings.append(reply['content']['rating']['value'])
                        raw_final_ratings.append(0)
                    confidence.append(reply['content']['confidence']['value'])
                else:
                    # Official comments - e.g. rebuttals
                    word_count = 0
                    for k, v in reply['content'].items():
                        if 'value' in v and type(v['value']) == str:
                            word_count += len(v['value'].split())
                    comment_word_count.append(word_count)

            elif signature.startswith("Area_Chair_") or signature.startswith("Senior_Area_Chair"):
                # Meta_reviews
                is_metareview = f'{venue_id}/Submission{s.number}/-/Meta_Review' in reply['invitations']
                if is_metareview:
                    word_count = 0
                    for k, v in reply['content'].items():
                        if 'value' in v and type(v['value']) == str:
                            word_count += len(v['value'].split())
                    meta_word_counts.append(word_count)

                    meta_decision.append(reply['content']['recommendation']['value'])
                    meta_confidence.append(reply['content']['confidence']['value'])

                else:
                    # Official comments - e.g., dicussions?
                    pass

            elif signature.startswith("Authors"):
                if f'{venue_id}/Submission{s.number}/-/Withdrawal' in reply['invitations']:
                    is_withdrawn = True
                elif f'{venue_id}/Submission{s.number}/-/Rebuttal' in reply['invitations']:
                    # Don't care about rebuttal
                    pass
                else:
                    # Should not print out anything here, actually...
                    print(reply)

            else:
                raise NotImplementedError(f"Unknown signature: {signature}")

        # Finally, if there is no decision, consider as rejected
        if decision is None:
            decision = "Reject"

        # NOTE: We only include 'valid' papers, which have at least one review
        if len(init_ratings) > 0:
            outputs.append({
                "submission_number": s.number,
                "title": s.content['title']['value'],
                "primary_area": primary_area,
                "decision": decision,
                "is_withdraw": is_withdrawn,
                "comment_word_count": ",".join(list(map(str, comment_word_count))),
                "review_word_counts": ",".join(list(map(str, word_counts))),
                "suitability": ",".join(list(map(str, suitability))),
                "confidence": ",".join(list(map(str, confidence))),
                "init_ratings": ",".join(list(map(str, init_ratings))),
                "final_ratings": ",".join(list(map(str, final_ratings))),
                "raw_final_ratings": ",".join(list(map(str, raw_final_ratings))),
                "meta_review_word_counts": ",".join(list(map(str, meta_word_counts))),
                "meta_review_decision": ",".join(list(map(str, meta_decision))),
                "meta_review_confidence": ",".join(list(map(str, meta_confidence))),
            })

    df = pd.DataFrame(outputs)
    df.to_excel(os.path.join(CACHE_DIR, 'data', 'valid_paper_all_detaills.xlsx'), index=False)

    review_name = venue_group.content['review_name']['value']
    reviews=[
        openreview.api.Note.from_json(reply)
        for s in submissions
        for reply in s.details['replies']
        if f'{venue_id}/{submission_name}{s.number}/-/{review_name}' in reply['invitations']
    ]

    with mp.Pool(16) as pool:
        outputs = list(tqdm(pool.imap(partial(process_review, client), reviews), total=len(reviews)))
    
    # Sequential version just for debugging
    # outputs = []
    # for i, review in enumerate(tqdm(reviews)):
    #     print(i, review.id)
    #     outputs.append(process_review(client, review))

    outputs = {k: v for elem in outputs for k, v in elem.items()}
    # sort by original key order, original means the one in the reviews
    keys = []
    for review in reviews:
        signature = review.signatures[0]
        sub_num, rev_id = signature.split('/')[-2:]
        sub_num = sub_num.split('Submission')[-1]
        rev_id = rev_id.split('Reviewer_')[-1]
        keys.append(tuple([sub_num, rev_id]))
    outputs = {k: outputs[k] for k in keys}

    # Get the range from previous year to next year
    curr_year = datetime.now().year
    prev_year = curr_year - 1
    next_year = curr_year + 1
    first_date = f'{next_year}-12-31'
    last_date = f'{prev_year}-01-01'

    for v in outputs.values():
        for date in v.keys():
            if date < first_date:
                first_date = date
            if date > last_date:
                last_date = date

    print("First date: ", first_date, "Last date: ", last_date)
    date_list = [first_date]
    date = datetime.strptime(first_date, "%Y-%m-%d")
    while date.strftime("%Y-%m-%d") != last_date:
        date += timedelta(days=1)
        date_list.append(date.strftime("%Y-%m-%d"))

    df_dict = {}
    for e in date_list:
        curr_lst = []
        for k, v in outputs.items():
            # find which interval we are at in v
            pt = 0
            while pt < len(v) and list(v.keys())[pt] < e:
                pt += 1
            if pt == 0:
                curr_lst.append(0)
            elif pt == len(v):
                curr_lst.append(list(v.values())[-1])
            else:
                curr_lst.append(list(v.values())[pt-1])
        df_dict[e] = curr_lst

    df = pd.DataFrame(df_dict)
    # set the output keys as the index column
    df.index = list(outputs.keys())
    df.to_excel(os.path.join(CACHE_DIR, "data", 'review_word_counts_over_time.xlsx'))


if __name__ == "__main__":
    main()

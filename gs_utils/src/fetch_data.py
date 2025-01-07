import os
import numpy as np
import concurrent
from src.utils import (
    get_venue_grp,
    get_submissions,
    get_user_info,
    words_count,
    process_submissions,
    calculate_global_progress
)
import pandas as pd
from src.constants import CACHE_DIR
import json
import openreview
import tqdm


def fetch_submission_data(client, venue_id, submission, submission_name, sac_name, ac_name, reviewer_name):
    # NOTE: Helper function for parallel processing
    results = {'ac2id': {}, 'id2reviewer': {}, 'sac2ac': {}}
    ac_key, rev_key, sac_key = None, None, None
    try:
        ac_group = client.get_group(f'{venue_id}/{submission_name}{submission.number}/{ac_name}')
        ac_members = ac_group.members
        # assert len(ac_members) <= 1, "Unexpected number of ACs: {} for {}".format(len(ac_members), submission.id)
        if not ac_members:
            results['ac2id']["Not assigned"] = [submission.id]
        else:
            for ac_key in ac_members:
                if ac_key not in results['ac2id']:
                    results['ac2id'][ac_key] = []
                results['ac2id'][ac_key].append(submission.id)
        
    except openreview.OpenReviewException:
        results['ac2id']["Not assigned"] = [submission.id]

    try:
        rev_group = client.get_group(f'{venue_id}/{submission_name}{submission.number}/{reviewer_name}')
        reviewers_members = rev_group.members
        reviewers_anons = [elem.split('/')[-1] for elem in rev_group.anon_members]
        assert len(reviewers_members) == len(reviewers_anons), "Number of reviewers and anons do not match"
        rev_key = submission.id if reviewers_members else "Not assigned"
        results['id2reviewer'][rev_key] = list(zip(reviewers_members, reviewers_anons)) if reviewers_members else []
    except openreview.OpenReviewException:
        results['id2reviewer']["Not assigned"] = []

    try:
        sac_group = client.get_group(f'{venue_id}/{submission_name}{submission.number}/{sac_name}')
        sac_members = sac_group.members
        # assert len(sac_members) <= 1, "Unexpected number of SACs: {} for {}".format(len(sac_members), submission.id)
        if not sac_members:
            results['sac2ac']["Not assigned"] = ac_members
        else:
            for sac_key in sac_members:
                results['sac2ac'][sac_key] = ac_members
    except openreview.OpenReviewException:
        # Case where a submission is not assigned to any SAC
        # In this case this submission is not assigned to any AC or reviewer
        assert ac_key is None, "Unexpected case: submission is not assigned to any SAC but is assigned to an AC"
        assert rev_key is None, "Unexpected case: submission is not assigned to any SAC but is assigned to a reviewer"

    return results


def fetch_submission_metadata(client):
    # NOTE: We have to construct the assignment info for ACs, SACs, and reviewers
    # Path for storing the assignment info
    base_dst = CACHE_DIR
    dst_ac2id = os.path.join(base_dst, 'assign_ac2id.json')
    dst_id2reviewer = os.path.join(base_dst, 'assign_id2reviewer.json')
    dst_sac2ac = os.path.join(base_dst, 'assign_sac2ac.json')
    dst_sac_info = os.path.join(base_dst, 'sac_info.json')
    dst_ac_info = os.path.join(base_dst, 'ac_info.json')
    dst_reviewer_info = os.path.join(base_dst, 'reviewer_info.json')
    os.makedirs(base_dst, exist_ok=True)

    # Load the credentials and the client
    venue_id = os.environ["OPENREVIEW_VENUE_ID"]
    venue_grp = get_venue_grp(client, venue_id)

    submission_name = venue_grp.content['submission_name']['value']
    sac_name = venue_grp.content['senior_area_chairs_name']['value']
    ac_name = venue_grp.content['area_chairs_name']['value']
    reviewer_name = venue_grp.content["reviewers_name"]["value"]

    # Get all submissions and do the basic processing
    submissions = get_submissions(client, venue_id, venue_grp)

    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as executor:
        # results is a list of dictionaries, each one is a single execution of fetch_submission_data
        results = list(
            tqdm.tqdm(
                executor.map(
                    fetch_submission_data,
                    [client]*len(submissions),
                    [venue_id]*len(submissions),
                    submissions,
                    [submission_name]*len(submissions),
                    [sac_name]*len(submissions),
                    [ac_name]*len(submissions),
                    [reviewer_name]*len(submissions)
                ),
                total=len(submissions)
            )
        )

    # Aggregate the results into two dictionaries
    ac2id = {}
    id2reviewer = {}
    sac2ac = {}

    for result in results:
        for key, value in result['ac2id'].items():
            if key not in ac2id:
                ac2id[key] = []
            ac2id[key].extend(value)

        for key, value in result['id2reviewer'].items():
            if key not in id2reviewer:
                id2reviewer[key] = []
            id2reviewer[key].extend(value)

        for key, value in result['sac2ac'].items():
            if key not in sac2ac:
                sac2ac[key] = set()
            sac2ac[key].update(value)

    # Set objects can't be serialized to json, cast to list instead
    for key in sac2ac:
        sac2ac[key] = list(sac2ac[key])

    # Get senior AC info
    sac_members = client.get_group(id=venue_grp.content['senior_area_chairs_id']['value']).members
    sac_info = get_user_info(client, sac_members)

    # Get AC info
    ac_members = client.get_group(id=venue_grp.content['area_chairs_id']['value']).members
    ac_info = get_user_info(client, ac_members)

    # Get reviewer info
    reviewer_members = client.get_group(id=venue_grp.content['reviewers_id']['value']).members
    reviewer_info = get_user_info(client, reviewer_members)

    # Save results as json
    with open(dst_ac2id, 'w') as f:
        json.dump(ac2id, f)

    with open(dst_id2reviewer, 'w') as f:
        json.dump(id2reviewer, f)

    with open(dst_sac2ac, 'w') as f:
        json.dump(sac2ac, f)

    with open(dst_sac_info, 'w') as f:
        json.dump(sac_info, f)

    with open(dst_ac_info, 'w') as f:
        json.dump(ac_info, f)

    with open(dst_reviewer_info, 'w') as f:
        json.dump(reviewer_info, f)


def fetch_review_rating(client):
    # NOTE: This function fetches the review ratings and saves them as CSV files, later uploaded to Google Sheets
    cache_path = CACHE_DIR
    dst_ac2id = os.path.join(cache_path, 'assign_ac2id.json')
    dst_id2reviewer = os.path.join(cache_path, 'assign_id2reviewer.json')

    save_path = os.path.join(cache_path, 'data')
    rating_data_path = os.path.join(save_path, 'rating')

    os.makedirs(rating_data_path, exist_ok=True)

    # Load all cached data
    with open(dst_ac2id, 'r') as f:
        ac2id = json.load(f)
    with open(dst_id2reviewer, 'r') as f:
        id2reviewer = json.load(f)

    # Load the credentials and the client
    venue_id = os.environ["OPENREVIEW_VENUE_ID"]
    venue_grp = get_venue_grp(client, venue_id)
    invalid_venue = [f'{venue_id}/Withdrawn_Submission',
                    f'{venue_id}/Desk_Rejected_Submission']
    submissions = get_submissions(client, venue_id, venue_grp)
    submissions_map = {submission.id: submission for submission in submissions}

    invalid_sub_ids = [submission.id for submission in submissions if submission.content['venueid']['value'] in invalid_venue]    

    # Define some OpenReview names
    submission_name = venue_grp.content['submission_name']['value']
    review_name = venue_grp.content['review_name']['value']

    # Prepare the column names
    max_reviewers = max([len(reviewers) for reviewers in id2reviewer.values()])
    col_names = ["Submission Number", "Rebuttal Submitted", "Avg Initial Rtng", "Avg Final Rtng"]
    for i in range(1, max_reviewers + 1):
        col_names.append(f"Rvw {i} Initial Rtng")
        col_names.append(f"Rvw {i} Final Rtng")

    for ac_id, sub_ids in ac2id.items():
        if ac_id == "Not assigned":
            continue

        status_rating = {col: [] for col in col_names}
        valid_sub_ids = [sub_id for sub_id in sub_ids if sub_id not in invalid_sub_ids]
        for sub_id in valid_sub_ids:
            submission = submissions_map[sub_id]
            status_rating["Submission Number"].append(submission.number)

            # Itertate through all comments to set variable value
            rebuttal_submitted = False
            # comment_count = 0
            ratings = {}
            for reply in submission.details['replies']:
                if f'{venue_id}/{submission_name}{submission.number}/-/{review_name}' in reply['invitations']:
                    # assert 'rating' in reply['content'], "Original Rating not found in the review"
                    reviewer_id = reply['writers'][-1].split('/')[-1]
                    init_rating, final_rating = None, None
                    if 'rating' in reply['content'] and 'value' in reply['content']['rating']:
                        init_rating = reply['content']['rating']['value']
                    if 'final_rating' in reply['content'] and 'value' in reply['content']['final_rating']:
                        final_rating = reply['content']['final_rating']['value']
                    ratings[reviewer_id] = (init_rating, final_rating)

                elif f'{venue_id}/{submission_name}{submission.number}/-/Rebuttal' in reply['invitations']:
                    # Contains the rebuttal feed
                    rebuttal_submitted = True

                # elif f'{venue_id}/{submission_name}{submission.number}/-/Official_Comment' in reply['invitations']:
                #     comment_count += 1

            status_rating["Rebuttal Submitted"].append(rebuttal_submitted)
            # status_rating["Comment Count"].append(comment_count)

            init_rating, init_count = 0, 0
            final_rating, final_count = 0, 0

            for i, reviewer_ids in enumerate(id2reviewer[sub_id]):
                _, reviewer_anon = reviewer_ids
                # We only account for the reviewers that have submitted a review and provide a rating
                # For those invited but not submitted, we will leave the values as None
                if reviewer_anon in ratings:
                    status_rating[f'Rvw {i+1} Initial Rtng'].append(ratings[reviewer_anon][0])
                    status_rating[f'Rvw {i+1} Final Rtng'].append(ratings[reviewer_anon][1])
                    init_rating += ratings[reviewer_anon][0]
                    init_count += 1
                    if ratings[reviewer_anon][1]:
                        # If the reviewer provides the final rating, we will use it
                        final_rating += ratings[reviewer_anon][1]
                        final_count += 1
                    else:
                        # If the final rating is not available, we will use the initial rating instead
                        final_rating += ratings[reviewer_anon][0]
                        final_count += 1
                else:
                    status_rating[f'Rvw {i+1} Initial Rtng'].append(None)
                    status_rating[f'Rvw {i+1} Final Rtng'].append(None)

            # Calculate the two average ratings
            status_rating["Avg Initial Rtng"].append(round(init_rating / init_count if init_count > 0 else 0, 3))
            status_rating["Avg Final Rtng"].append(round(final_rating / final_count if final_count > 0 else 0, 3))

            for i in range(len(id2reviewer[sub_id]), max_reviewers):
                status_rating[f'Rvw {i+1} Initial Rtng'].append(None)
                status_rating[f'Rvw {i+1} Final Rtng'].append(None)
        status_rating = pd.DataFrame(status_rating).sort_values(by='Rebuttal Submitted', ascending=False)
        status_rating.to_csv(os.path.join(rating_data_path, f'{ac_id}.csv'), index=False)


def fetch_review_wordcount(client):
    """
    This script is used to generate the paper assignment for ACs. Data are stored as 
    CSV or Json files in the cache folder. The columns are as follows:
    - Forum ID: The ID of the submission
    - Submission Number: The submission number
    - Reviewer i ID: The ID of the reviewer i
    - Reviewer i Word Count: The word count of the review of reviewer i
    Later this will be uploaded to Google Sheets
    """
    cache_path = CACHE_DIR
    dst_ac2id = os.path.join(cache_path, 'assign_ac2id.json')
    dst_id2reviewer = os.path.join(cache_path, 'assign_id2reviewer.json')

    # Load all cached data
    with open(dst_ac2id, 'r') as f:
        ac2id = json.load(f)
    with open(dst_id2reviewer, 'r') as f:
        id2reviewer = json.load(f)

    # Load the credentials and the client
    venue_id = os.environ["OPENREVIEW_VENUE_ID"]
    venue_grp = get_venue_grp(client, venue_id)

    # Get all submissions and do the basic processing
    submissions = get_submissions(client, venue_id, venue_grp)
    processed_subs = process_submissions(submissions, venue_grp, venue_id)

    # Get withdrawn / desk rejected submissions
    invalid_venue = [f'{venue_id}/Withdrawn_Submission',
                     f'{venue_id}/Desk_Rejected_Submission']
    invalid_sub_ids = [submission.id for submission in submissions if submission.content['venueid']['value'] in invalid_venue]

    # Apply the word_counter function to the reviews
    for s_key, s in processed_subs.items():
        processed_subs[s_key]['reviews_word_count'] = {}
        for reviewer_id, review_content in s['reviews'].items():
            processed_subs[s_key]['reviews_word_count'][reviewer_id] = words_count(review_content)

    # Get the submission data/info, use the maximum number of reviewers possible
    # col_names = ["Forum ID", "Submission Number"]
    col_names = ["Submission Number", "Action?"]
    max_reviewers = max([len(reviewers) for reviewers in id2reviewer.values()])
    for i in range(1, max_reviewers + 1):
        # col_names.append(f"Reviewer {i} ID")
        col_names.append(f"Reviewer {i}")

    col_names_reviewer_info = ["Submission Number"]
    for i in range(1, max_reviewers + 1):
        col_names_reviewer_info.append(f"Reviewer {i}")

    ac2wordcount = {}
    ac2reviewerinfo = {}
    ac2reviewprogress = {}
    ac2paperprogress = {}

    for ac_id, sub_ids in ac2id.items():
        # Skip the ACs that are not assigned
        if ac_id == 'Not assigned':
            continue

        wordcount = {col: [] for col in col_names}
        reviewerinfo = {col: [] for col in col_names_reviewer_info}

        # We only care about active submissions
        valid_sub_ids = [sub_id for sub_id in sub_ids if sub_id not in invalid_sub_ids]

        reviews_current = 0
        reviews_total = 0
        paper_completed_current = 0
        paper_total = 0

        # Iterate through all valid submissions
        for sub_id in valid_sub_ids:
            # Get the results for the progress statistics
            reviews_current += len(processed_subs[sub_id]['reviews'])
            reviews_total += len(id2reviewer[sub_id])
            paper_completed_current += 1 if len(processed_subs[sub_id]['reviews']) >= 3 else 0
            paper_total += 1

            # Two attributes: Forum ID and Submission Number
            wordcount["Submission Number"].append(processed_subs[sub_id]['submission_number'])
            reviewerinfo["Submission Number"].append(processed_subs[sub_id]['submission_number'])

            assert sub_id in id2reviewer, f"Submission {sub_id} has no reviewers assigned!"

            # Iterate through all reviewers
            for i, reviewer_ids in enumerate(id2reviewer[sub_id]):
                # The reviewer has a real name and also an anonymous name
                reviewer_real, reviewer_anon = reviewer_ids

                reviewerinfo[f"Reviewer {i+1}"].append(reviewer_real)

                # Get the review word count of that reviewer
                reviews_word_count = processed_subs[sub_id]['reviews_word_count']
                if reviewer_anon in reviews_word_count:
                    wordcount[f"Reviewer {i+1}"].append(reviews_word_count[reviewer_anon])
                else:
                    wordcount[f"Reviewer {i+1}"].append(0)

            # Fill remaining reviewer_word_count columns with nan
            for i in range(len(id2reviewer[sub_id]), max_reviewers):
                reviewerinfo[f"Reviewer {i+1}"].append(np.nan)
                wordcount[f"Reviewer {i+1}"].append(np.nan)

            # Initialize Action? as empty string
            wordcount["Action?"].append('')

        ac2wordcount[ac_id] = pd.DataFrame(wordcount)
        ac2reviewerinfo[ac_id] = pd.DataFrame(reviewerinfo)
        ac2reviewprogress[ac_id] = {"current": reviews_current, "total": reviews_total}
        ac2paperprogress[ac_id] = {"current": paper_completed_current, "total": paper_total}

    data_path = os.path.join(cache_path, 'data')
    word_count_path = os.path.join(data_path, 'word_count')
    reviewerinfo_path = os.path.join(data_path, 'reviewer_info')
    review_progress_path = os.path.join(data_path, 'review_progress')
    paper_progress_path = os.path.join(data_path, 'paper_progress')
    global_progress_path = os.path.join(data_path, 'global_progress')
    os.makedirs(word_count_path, exist_ok=True)
    os.makedirs(reviewerinfo_path, exist_ok=True)
    os.makedirs(review_progress_path, exist_ok=True)
    os.makedirs(paper_progress_path, exist_ok=True)
    os.makedirs(global_progress_path, exist_ok=True)

    # Save the wordcount spreadsheets as csv
    for ac_id, wordcount in ac2wordcount.items():
        wordcount.to_csv(os.path.join(word_count_path, f"{ac_id}.csv"), index=False)

    # Save the reviewer info as csv
    for ac_id, reviewerinfo in ac2reviewerinfo.items():
        reviewerinfo.to_csv(os.path.join(reviewerinfo_path, f"{ac_id}.csv"), index=False)

    # Save the review progress as json
    for ac_id, reviewprogress in ac2reviewprogress.items():
        with open(os.path.join(review_progress_path, f"{ac_id}.json"), 'w') as f:
            json.dump(reviewprogress, f)

    # Save the paper progress as json
    for ac_id, paperprogress in ac2paperprogress.items():
        with open(os.path.join(paper_progress_path, f"{ac_id}.json"), 'w') as f:
            json.dump(paperprogress, f)

    # Calculate paper global progress
    paper_global_progress = calculate_global_progress(ac2paperprogress)
    with open(os.path.join(global_progress_path, "paper_global_progress.json"), 'w') as f:
        json.dump(paper_global_progress, f)

    # Calculate review global progress
    review_global_progress = calculate_global_progress(ac2reviewprogress)
    with open(os.path.join(global_progress_path, "review_global_progress.json"), 'w') as f:
        json.dump(review_global_progress, f)


def fetch_missing_metareview(client):
    # NOTE: This can be helpful when PCs want the check whether the metareview has been provided from ACs, this won't be uploaded to Google Sheets
    cache_path = CACHE_DIR
    dst_ac2id = os.path.join(cache_path, 'assign_ac2id.json')
    dst_sac2ac = os.path.join(cache_path, 'assign_sac2ac.json')

    save_path = os.path.join(cache_path, 'data')
    os.makedirs(save_path, exist_ok=True)

    # Load all cached data
    with open(dst_ac2id, 'r') as f:
        ac2id = json.load(f)
    with open(dst_sac2ac, 'r') as f:
        sac2ac = json.load(f)

    # Load the credentials and the client
    venue_id = os.environ["OPENREVIEW_VENUE_ID"]
    venue_grp = get_venue_grp(client, venue_id)
    invalid_venue = [f'{venue_id}/Withdrawn_Submission',
                    f'{venue_id}/Desk_Rejected_Submission']
    submissions = get_submissions(client, venue_id, venue_grp)
    submissions_map = {submission.id: submission for submission in submissions}

    invalid_sub_ids = [submission.id for submission in submissions if submission.content['venueid']['value'] in invalid_venue]    

    # Define some OpenReview names
    submission_name = venue_grp.content['submission_name']['value']
    meta_review_name = venue_grp.content['meta_review_name']['value']

    # Prepare the column names
    col_names = ["AC ID", "SAC ID", "# Missing Metareviews", "Submissions Missing"]
    missing_metareview = {col: [] for col in col_names}

    for ac_id, sub_ids in ac2id.items():
        if ac_id == "Not assigned":
            continue

        missing_subs = []
        valid_sub_ids = [sub_id for sub_id in sub_ids if sub_id not in invalid_sub_ids]
        for sub_id in valid_sub_ids:
            submission = submissions_map[sub_id]

            has_metareview = False
            for reply in submission.details['replies']:
                if f'{venue_id}/{submission_name}{submission.number}/-/{meta_review_name}' in reply['invitations']:
                    has_metareview = True
                    break
            
            if not has_metareview:
                missing_subs.append(str(submission.number))

        if len(missing_subs) > 0:
            missing_metareview["AC ID"].append(ac_id)
            missing_metareview["# Missing Metareviews"].append(len(missing_subs))
            missing_metareview["Submissions Missing"].append(", ".join(missing_subs))
            sac_id = [sac for sac, ac_list in sac2ac.items() if ac_id in ac_list]
            missing_metareview["SAC ID"].append(", ".join(sac_id))

    df = pd.DataFrame(missing_metareview)
    df.to_csv(os.path.join(save_path, 'missing_metareview.csv'), index=False)


def fetch_recommendation_outliers(client):
    # NOTE: This crawls the data from OpenReview and analyze the outliers in the recommendation, it won't be uploaded to Google Sheets
    cache_path = CACHE_DIR
    venue_id = os.environ["OPENREVIEW_VENUE_ID"]
    venue_grp = get_venue_grp(client, venue_id)
    submissions = get_submissions(client, venue_id, venue_grp)
    submissions_map = {s.id: s for s in submissions}

    submission_name = venue_grp.content['submission_name']['value']
    review_name = venue_grp.content['review_name']['value']
    metareview_name = venue_grp.content['meta_review_name']['value']
    invalid_venue = [f'{venue_id}/Withdrawn_Submission',
                    f'{venue_id}/Desk_Rejected_Submission']

    with open(os.path.join(cache_path, 'assign_ac2id.json'), 'r') as f:
        assign_ac2id = json.load(f)
    with open(os.path.join(cache_path, 'assign_sac2ac.json'), 'r') as f:
        assign_sac2ac = json.load(f)

    out = {"Submission Number": [], "Scores": [], "Recommendation": [], "Area Chair(s)": [], "Senior Area Chair(s)": [], "Reason": []}
    processed_paper_numbers = set()

    for ac_id, sub_ids in assign_ac2id.items():
        for sub_id in sub_ids:
            submission = submissions_map[sub_id]
            if submission.content['venueid']['value'] in invalid_venue:
                continue

            if submission.number in processed_paper_numbers:
                continue

            processed_paper_numbers.add(submission.number)

            # Get all final ratings
            final_ratings = []
            meta_reviews = []
            
            for reply in submission.details['replies']:
                if f'{venue_id}/{submission_name}{submission.number}/-/{review_name}' in reply['invitations']:
                    assert 'rating' in reply['content'], "Original Rating not found in the review"
                    reviewer_id = reply['writers'][-1].split('/')[-1]
                    if 'final_rating' in reply['content'] and 'value' in reply['content']['final_rating']:
                        # if final rating exists, use final rating
                        final_ratings.append(reply['content']['final_rating']['value'])
                    else:
                        # if final rating does not exist, use original rating
                        final_ratings.append(reply['content']['rating']['value'])

                if f'{venue_id}/{submission_name}{submission.number}/-/{metareview_name}' in reply['invitations']:
                    meta_reviews.append((reply['signatures'][0].split("/")[-1], reply['content']['recommendation']['value']))
            
            if len(meta_reviews) > 1:
                recommendations = [meta_review[1] for meta_review in meta_reviews]
                if all(recommendation == recommendations[0] for recommendation in recommendations):
                    recommendation = recommendations[0]
                elif any(recommendation != recommendations[0] for recommendation in recommendations):
                    # Program chair first, then Senior Area chair, then Area_chair
                    reviews_map = dict(meta_reviews)
                    if "Program_Chairs" in reviews_map:
                        recommendation = reviews_map["Program_Chairs"]
                    elif "Senior_Area_Chairs" in reviews_map:
                        recommendation = reviews_map["Senior_Area_Chairs"]
                    else:
                        print(f"Submission {submission.number} has multiple different recommendations from Area Chairs")
            elif len(meta_reviews) == 0:
                recommendation = None
            elif len(meta_reviews) == 1:
                recommendation = meta_reviews[0][1]

            # NOTE: Customize the logic for outlier detection here...
            # Case 1: No recommendation, put into output.
            if recommendation is None:
                out['Submission Number'].append(submission.number)
                out['Scores'].append(', '.join(list(map(str, final_ratings))))
                out['Recommendation'].append('N/A')
                out['Area Chair(s)'].append(ac_id)
                sacs = [elem for elem, ac_ids in assign_sac2ac.items() if ac_id in ac_ids]
                out['Senior Area Chair(s)'].append(', '.join(sacs))
                out['Reason'].append('No recommendation found')
                continue

            high_scored = np.mean(final_ratings) >= 4
            low_scored = np.mean(final_ratings) < 3.
            # accept_scores = [score for score in final_ratings if score > 3.5]
            # reject_scores = [score for score in final_ratings if score <= 3.5]

            outlier = False
            # Case 2: scored more than 4, but rejected
            if high_scored and 'Reject' in recommendation:
                outlier = True
                reason = 'Avg score > 4, but rejected by AC'

            # Case 3: scored less than 3., but accepeted
            if low_scored and 'Accept' in recommendation:
                outlier = True
                reason = 'Avg score < 3., but accepted by AC'

            # Case 4: Most accept score, but rejected by AC
            # if len(accept_scores) > len(reject_scores) and 'Reject' in recommendation:
            #     outlier = True
            #     reason = 'More accept scores by reviewers, but rejected by AC'

            # Case 5: Most reject score, but accepted by AC
            # if len(reject_scores) > len(accept_scores) and 'Accept' in recommendation:
            #     outlier = True
            #     reason = 'More reject scores by reviewers, but accepted by AC'

            if outlier:
                out['Submission Number'].append(submission.number)
                out['Scores'].append(', '.join(list(map(str, final_ratings))))
                out['Recommendation'].append(recommendation)
                out['Area Chair(s)'].append(ac_id)
                sacs = [elem for elem, ac_ids in assign_sac2ac.items() if ac_id in ac_ids]
                out['Senior Area Chair(s)'].append(', '.join(sacs))
                out['Reason'].append(reason)

    out = pd.DataFrame(out)
    # Sort the Recommendation column, keep all 'N/A' to the bottom
    out = out.sort_values(by=['Recommendation'], key=lambda x: x.replace('N/A', 'ZZZ'))

    # Upload out to google sheet
    output_path = os.path.join(cache_path, 'data', 'recommendation_outlier.csv')
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    out.to_csv(output_path, index=False)

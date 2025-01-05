#!/usr/bin/env python3

import collections
import getpass
import openreview
import sys
import os
import csv
import statistics

conf_id = "acmmm.org/ACMMM/2024/Conference/"

# Login for users
def login(default_username):
    username = input(f"Username [{default_username}]: ") or default_username
    password = getpass.getpass()
    return username, password

# Get an openreview client
def get_client():
    return openreview.api.OpenReviewClient(
        baseurl='https://api2.openreview.net',
        username="lyadanluol@gmail.com",
        password="langlang427739"
    )

# Get profiles of Senior Area Chairs (SAC)
def get_sac_profiles(client):
    sacs = client.get_group(conf_id + "Senior_Area_Chairs")
    profiles = openreview.tools.get_profiles(
        client, ids_or_emails=sacs.members, with_publications=True
    )
    print("SACs=", len(profiles), file=sys.stderr)
    return profiles

# Get profiles of Area Chairs (AC)
def get_ac_profiles(client):
    acs = client.get_group(conf_id + "Area_Chairs")
    profiles = openreview.tools.get_profiles(
        client, ids_or_emails=acs.members, with_publications=True
    )
    print("ACs=", len(profiles), file=sys.stderr)
    return profiles

# Get profiles of Reviewers
def get_r_profiles(client):
    reviewers = client.get_group(conf_id + "Reviewers")
    profiles = openreview.tools.get_profiles(
        client, ids_or_emails=reviewers.members, with_publications=True
    )
    print("Reviewers=", len(profiles), file=sys.stderr)
    return profiles

# Profile validation check
def profile_check(profiles):
    for profile in profiles:
        email = profile.content.get('preferredEmail', 'N/A')
        name = " ".join(
            [profile.content['names'][0].get(k, "") for k in ['first', 'last']]
        ) if 'names' in profile.content else "NONE"
        affiliation = next(
            (h['institution']['name'] for h in profile.content.get('history', [])
             if h.get('end') is None),
            "NONE"
        )
        if name == "NONE" or affiliation == "NONE":
            print(f"{profile.id}\t{email}\t{name}\t{affiliation}")

# Submission statistics by track
def submission_stats(client):
    submissions = client.get_all_notes(invitation=conf_id + "-/Submission")
    total, total_pdf = len(submissions), sum('pdf' in sub.content for sub in submissions)
    print('Total Submissions:', total, 'Total PDFs:', total_pdf)

# Submission statistics by country
def submission_country_stats(client):
    map_domain_country = {}
    with open('map_domain_country.csv') as f:
        for domain, country in csv.reader(f):
            map_domain_country[domain.strip()] = country.strip()
    
    submissions = client.get_all_notes(invitation=conf_id + "-/Submission")
    for sub in submissions:
        author_id = sub.content['authorids']['value'][0]
        profile = client.get_profile(author_id)
        email_domain = profile.content.get('preferredEmail', 'N/A').split('@')[-1].split('.')[-1]
        country = map_domain_country.get(email_domain, 'Unknown')
        if 'pdf' in sub.content and 'Withdrawn' not in sub.content['venueid']['value']:
            print(sub.number, country)

# Main execution
def main():
    client = get_client()
    sac_profiles = get_sac_profiles(client)
    ac_profiles = get_ac_profiles(client)
    r_profiles = get_r_profiles(client)
    profile_check(sac_profiles + ac_profiles + r_profiles)
    submission_stats(client)
    
if __name__ == "__main__":
    main()

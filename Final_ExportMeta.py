import xml.dom.minidom
import openreview
import xml.etree.ElementTree as ET


import time
import pandas as pd
import multiprocessing as mp
from multiprocessing import Pool
from tqdm import tqdm
import pandas as pd
import requests


# Load the author emails and decisions Excel file
# file_path = './author_emails_decisions.xlsx'
# author_emails_decisions = pd.read_excel(file_path)

# Authenticate with OpenReview
client = openreview.api.OpenReviewClient(
    baseurl='https://api2.openreview.net',
    username="",  # YOUR OPENREVIEW USERNAME e.g., email
    password=""  # YOUR OPENREVIEW PASSWD
)


# Define the conference ID and the accepted papers invitation ID
venue_id = 'acmmm.org/ACMMM/2024/Conference'  # 'acmmm.org/ACMMM/2024/Track/Demo'
venue_group = client.get_group(venue_id)
submission_name = venue_group.content['submission_name']['value']
track_name = 'main'  # BNI, GC, Demo

# notes = client.get_all_notes(
#     invitation=f'{venue_id}/-/{submission_name}', details='replies')  # [:20] for debugging
notes = client.get_all_notes(content={'venueid': venue_id})

# Create a new XML tree structure with parent data
new_root = ET.Element('erights_record')

# Add parent_data
parent_data = ET.SubElement(new_root, 'parent_data')
proceeding = ET.SubElement(parent_data, 'proceeding')
proceeding.text = str(venue_id)  # Ensure this is a string

volume = ET.SubElement(parent_data, 'volume')
volume.text = ''
issue = ET.SubElement(parent_data, 'issue')
issue.text = ''
issue_date = ET.SubElement(parent_data, 'issue_date')
issue_date.text = ''
source = ET.SubElement(parent_data, 'source')
source.text = ''

for note in tqdm(notes):
    paper = ET.SubElement(new_root, 'paper')

    paper_type = ET.SubElement(paper, 'paper_type')
    paper_type.text = 'Full Paper'  # You can adjust this as per your requirements

    art_submission_date = ET.SubElement(paper, 'art_submission_date')
    art_submission_date.text = ''
    art_approval_date = ET.SubElement(paper, 'art_approval_date')
    art_approval_date.text = ''

    paper_title = ET.SubElement(paper, 'paper_title')
    paper_title.text = note.content.get('title', 'N/A')['value']

    event_tracking_number = ET.SubElement(paper, 'event_tracking_number')
    event_tracking_number.text = str(note.number)

    published_article_number = ET.SubElement(paper, 'published_article_number')
    published_article_number.text = ''
    start_page = ET.SubElement(paper, 'start_page')
    start_page.text = ''
    end_page = ET.SubElement(paper, 'end_page')
    end_page.text = ''

    authors_element = ET.SubElement(paper, 'authors')
    authors_list = [] if not note.content.get(
        'authorids') else note.content['authorids']['value']

    for i, author_id in enumerate(authors_list):
        # profile = client.get_profile(author_id)
        profile = openreview.tools.get_profiles(client, [author_id])

        # Those "ghost" users...
        if len(profile) == 0:
            print(f"Profile not found for {author_id}")
            continue
        profile = profile[0]

        author = ET.SubElement(authors_element, 'author')

        prefix = ET.SubElement(author, 'prefix')
        prefix.text = ''

        first_name = ET.SubElement(author, 'first_name')
        first_name.text = profile.content.get(
            'names', [{}])[0].get('first', 'N/A')

        middle_name = ET.SubElement(author, 'middle_name')
        middle_name.text = ''

        last_name = ET.SubElement(author, 'last_name')
        last_name.text = profile.content.get(
            'names', [{}])[0].get('last', 'N/A')

        suffix = ET.SubElement(author, 'suffix')
        suffix.text = ''

        # for those user who do not set first and last name
        if first_name.text == 'N/A' and last_name.text == 'N/A':
            full_name = profile.content.get(
                'names', [{}])[0].get('fullname', 'N/A')
            parts = full_name.strip().split()
            first_name.text = " ".join(parts[:-1])
            last_name.text = parts[-1]

        affiliations = ET.SubElement(author, 'affiliations')
        institution_info = profile.content.get(
            'history', [{}])[0].get('institution', {}).get('name', 'N/A')
        affiliation = ET.SubElement(affiliations, 'affiliation')
        institution = ET.SubElement(affiliation, 'institution')

        sequence_no = ET.SubElement(author, 'sequence_no')
        sequence_no.text = str(i+1)

        institution.text = institution_info

        city = ET.SubElement(affiliation, 'city')
        city.text = ''
        state_province = ET.SubElement(affiliation, 'state_province')
        state_province.text = ''
        country = ET.SubElement(affiliation, 'country')
        country.text = ''

        # only consider one institute per author
        institute_sequence_no = ET.SubElement(affiliation, 'sequence_no')
        institute_sequence_no.text = '1'

        email_address = ET.SubElement(author, 'email_address')

        email = profile.content.get('preferred_email', 'N/A')

        # handle for those who did not set preferred emails
        if email == 'N/A':
            email = profile.content.get('emails', ['N/A'])[0]
        email_address.text = email

        # first author as contact author
        contact_author = ET.SubElement(author, 'contact_author')
        contact_author.text = 'Y' if i == 0 else 'N'

        ACM_profile_id = ET.SubElement(author, 'ACM_profile_id')
        ACM_profile_id.text = ''
        ACM_client_no = ET.SubElement(author, 'ACM_client_no')
        ACM_client_no.text = ''

        ORCID = ET.SubElement(author, 'ORCID')
        ORCID.text = profile.content.get(
            'orcid', ' ')
        if ORCID.text != 'N/A':
            ORCID.text = ORCID.text.split('/')[-1]


# Convert the new XML tree to a string
new_tree = ET.ElementTree(new_root)
new_tree.write('{}_paperLoad.xml'.format('_'.join(venue_id.split(
    '/')[1:] + [track_name])), encoding='utf-8', xml_declaration=True)

print("XML data export completed.")

# Pretty print the XML


def pretty_print_xml(elem):
    rough_string = ET.tostring(elem, 'utf-8')
    reparsed = xml.dom.minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent=" ")


pretty_xml_as_string = pretty_print_xml(new_root)


# Save the pretty printed XML to a file
new_xml_file_path = '{}_paperLoad.xml'.format('_'.join(venue_id.split(
    '/')[1:] + [track_name]))
with open(new_xml_file_path, 'w', encoding='utf-8') as f:
    f.write(pretty_xml_as_string)

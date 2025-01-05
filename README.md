
# Guide to Publication Chair

Welcome to the Guide to Publication Chair repository. This repository is designed to assist publication chairs for any conference under the ACM umbrella. This repository provides useful tips and Python scripts to help prepare camera-ready information and fetch meta-information from the OpenReview system, converting it into the desired XML format.

## Tips Before the Final Submission Due Date

To minimize issues when processing meta-information:

- **Preferred Email**: Inform authors to mark their preferred email in their profiles and ensure their emails are functional. This is crucial as these emails will be used to receive the final submission link and review form. Guidance can be found [here](https://docs.openreview.net/getting-started/creating-an-openreview-profile/add-or-remove-an-email-address-from-your-profile).

- **Name Verification**: Ensure authors double-check that their first and last names are set correctly and in English.

- **Author Profiles**: Verify that all author profiles are correctly created and activated. Incorrect activation can lead to "ghost authors," requiring manual correction.

- **ORCID Linking**: Encourage authors to link their ORCID profiles. While optional, early action is beneficial.

- **Author Guidelines**: Clearly state in the author guidelines, as per ACM policy, that no changes in author order or additions/deletions of authors are allowed after submission. It is advisable to declare this on the official website.

### Communicating with Track Chairs

Encourage all track chairs (e.g., demo tracks, workshop tracks) to use OpenReview and follow the same LaTeX template as the main track. This allows you to forward them the Python script to fetch and convert data. Manual editing of the XML file often leads to inconsistency issues.

## Why Do We Need This XML File?
The publication process can often be unclear, so here is a clarification of the general procedure for publications in ACM proceedings:

1. The publication chair needs to forward the **XML files from all tracks** to the Sheridan Communications Team. They use an internal system to load all author information and create unique links for final submission. The critical **DOI string** will also be sent to finalize the version.
2. The **rightsreview form** will be sent to the main contact (the first author is set as the main contact by default).
3. The Sheridan Team will then monitor the process, checking formats and any issues to ensure all requirements are met.

Keep in mind that the XML file needs to be sent as soon as possible to allow authors enough time for any necessary revisions if mistakes are made.



## Use the Script (ExportMeta_toXML.py) 
This script fetches the information of all accepted papers and converts it into the **desired XML format** (see the sample file: `paperLoadSample.xml`).

Do ensure you have a **PC role** in the OpenReview system to fetch the data.

### Prerequisites

Python 3.6 or newer is required to use openreview-py. Python 2.7 is no longer supported.

### Installation

To install the OpenReview Python library:
```bash
pip install openreview-py
```

### Configuration

Replace your `username` and `password`:
```python
client = openreview.api.OpenReviewClient(
    baseurl='https://api2.openreview.net',
    username="",  # YOUR OPENREVIEW USERNAME, e.g., email
    password=""   # YOUR OPENREVIEW PASSWORD
)
```

### Define the Conference ID

Replace `venue_id` with your conference ID:
```python
venue_id = 'acmmm.org/ACMMM/2024/Conference'  # e.g., 'acmmm.org/ACMMM/2024/Track/Demo'
venue_group = client.get_group(venue_id)
submission_name = venue_group.content['submission_name']['value']
track_name = 'main'  # Other options: BNI, GC, Demo
```

After running the script, the papers should be correctly fetched and converted into the XML file.



### Additional Functionalities (other_func.py)

The other_func.py script provides additional features to assist publication chairs by managing and validating reviewer and chair profiles, as well as gathering submission statistics.

Key Functions:

**Profile Validation:**

- Validates profiles for Senior Area Chairs (SAC), Area Chairs (AC), and Reviewers.

- Checks for missing email addresses, incorrect name formats, and affiliation gaps.

**Submission Statistics:**

- Provides total counts of submissions and PDFs.

- Generates statistics by country based on submission author email domains.


### Acknowledgement
Thanks for the help of Xingjian Leng (xingjian.leng@anu.edu.au).
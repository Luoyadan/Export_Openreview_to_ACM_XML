
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

## How to Use the Python Code

Ensure you have a PC role in the OpenReview system to fetch the data.

### Prerequisites

Python 3.6 or newer is required to use openreview-py. Python 2.7 is no longer supported.

### Installation

To install the OpenReview Python library:
```bash
pip install openreview-py
```

### Configuration

Replace your username and password:
```python
client = openreview.api.OpenReviewClient(
    baseurl='https://api2.openreview.net',
    username="",  # YOUR OPENREVIEW USERNAME, e.g., email
    password=""   # YOUR OPENREVIEW PASSWORD
)
```

### Define the Conference ID

Replace \`venue_id\` with your conference ID:
```python
venue_id = 'acmmm.org/ACMMM/2024/Conference'  # e.g., 'acmmm.org/ACMMM/2024/Track/Demo'
venue_group = client.get_group(venue_id)
submission_name = venue_group.content['submission_name']['value']
track_name = 'main'  # Other options: BNI, GC, Demo
```

After running the script, the papers should be correctly fetched and converted into the XML file.

### Acknowledgement
Thanks for the help of Xingjian Leng (xingjian.leng@anu.edu.au).
# 🎓 Guide to Publication Chair & TPC

Welcome to the Guide to Publication Chair & Technical Program Committee (TPC) repository! This repository is designed to assist both publication chairs and TPC members involved in ACM conferences by providing essential tips, Python scripts, and integrations to streamline the publication and review processes.

---

## 📄 Section 1: Guide to Publication Chair

### 🛠️ Tips Before Final Submission Due Date

🔹 **Preferred Email:** Instruct authors to mark their preferred email in their profiles and ensure it is functional. This email will be used to receive the final submission link and review form. [More Info](https://docs.openreview.net/getting-started/creating-an-openreview-profile/add-or-remove-an-email-address-from-your-profile).

🔹 **Name Verification:** Ensure authors verify that their first and last names are correctly set and in English.

🔹 **Author Profiles:** Confirm all author profiles are correctly created and activated. Incomplete profiles can lead to "ghost authors," requiring manual corrections.

🔹 **ORCID Linking:** Encourage authors to link their ORCID profiles. While optional, early action prevents delays.

🔹 **Author Guidelines:** As per ACM policy, no changes to author order or additions/deletions are allowed post-submission. Clearly state this in author guidelines and on the official website.

### 📬 Communication with Track Chairs

Ensure track chairs (e.g., demo, workshop) use OpenReview and follow the same LaTeX template as the main track. This simplifies the process and prevents XML inconsistencies.

---

### 📂 Why XML Files are Needed

The publication chair must forward **XML files from all tracks** to the Sheridan Communications Team. This allows the team to load author information and generate unique submission links. 

**Process Overview:**
1. XML files are submitted to Sheridan Communications.
2. Sheridan generates the DOI string and final submission links.
3. The **rights review form** is sent to the first author (default main contact).
4. Sheridan monitors the process to ensure formatting and other requirements are met.

⏳ **Tip:** Send XML files early to give authors time for revisions if needed.

---

### 🧰 Scripts and Tools

#### 📜 ExportMeta_toXML.py
Fetches accepted paper information and converts it into the required XML format (sample: `paperLoadSample.xml`). Ensure you have **PC role** permissions in OpenReview.

**Prerequisites:**
- Python 3.6 or newer
- Install OpenReview Python library:
```bash
pip install openreview-py
```

**Configuration:**
```python
client = openreview.api.OpenReviewClient(
    baseurl='https://api2.openreview.net',
    username='',  # Your OpenReview email
    password=''   # Your OpenReview password
)
```
Replace `venue_id` with your conference ID:
```python
venue_id = 'acmmm.org/ACMMM/2024/Conference'
venue_group = client.get_group(venue_id)
submission_name = venue_group.content['submission_name']['value']
track_name = 'main'  # e.g., BNI, GC, Demo
```

---

## 📊 Section 2: Guide to TPC (Technical Program Committee)

Source code can be found in ```gs_utils``` folder.
### 📈 OpenReview - Google Sheets Integration

This section contains tools for integrating OpenReview with Google Sheets for the MM'24 conference. The integration allows for automated sheet creation and updates for submission data, assisting Area Chairs, SACs, and Program Chairs.

### ⚙️ Setup

Install required packages:
```bash
conda env create -f environment.yml
conda activate openreview
```

#### 🔐 Configuration

1. Create a Google Sheets API project and follow [these instructions](https://docs.gspread.org/en/latest/oauth2.html#for-end-users-using-oauth-client-id) to get credentials.
2. Create an `.env` file and add the following:
```sh
OPENREVIEW_VENUE_ID='acmmm.org/CONFERENCE/YEAR/Conference'
OPENREVIEW_USERNAME='OPENREVIEW_EMAIL'
OPENREVIEW_PASSWORD='OPENREVIEW_PASSWORD'
GOOGLE_CREDENTIALS_PATH='./credentials/CREDENTIALS.json'
GOOGLE_REFRESH_TOKEN_PATH='./credentials/REFRESH_TOKEN.refresh_token'
GOOGLE_ACCOUNT='YOUR_EMAIL'
```
3. Generate a refresh token:
```bash
python generate_refresh_token.py
```

4. Start data crawling and Google Sheets updates:
```bash
python gs_main.py
```

5. Broadcast the Google Sheets link to chairs:
```bash
python email_broadcast_main.py
```

6. For comprehensive submission data and trends:
```bash
python comprehensive_data_main.py
```

---

## ❓ FAQs

- **🔄 Google Sheets Update Failures:** Adjust `API_CREATE_LIMIT`, `API_UPDATE_LIMIT`, and `WAIT_TIME` in `src/constants.py` to avoid rate limits.
- **🔑 Authentication Issues:** If Google Sheets authentication expires, rerun `generate_refresh_token.py`.

---

## 🙏 Contact and Acknowledgement
We extend our gratitude to the MM'24 Organization Team. For any inquiries, feel free to reach out to:
**Yadan Luo** (y.luo@uq.edu.au) 
**Xingjian Leng** (xingjian.leng@anu.edu.au) 

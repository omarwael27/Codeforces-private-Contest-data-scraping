# Codeforces private Contest data scraping

**Automated system for aggregating and managing Codeforces private contest results across multiple events**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## Problem

Managing multiple Codeforces contests and aggregating results is time-consuming and error-prone. Previously, this required:

- Manual data entry from multiple contest pages
- 4-5 hours of work to aggregate and filter results
- Frequent human errors in data collection
- Manual spreadsheet updates across multiple sheets
- Tedious filtering and formatting
- Difficulty tracking performance across contests

### Note: Private Contests Only

This tool is designed specifically for **private Codeforces contests** (group contests). Public contests can use the official [Codeforces API](https://codeforces.com/apiHelp) for easier automation. Private contests don't have API access, making web scraping the only practical solution.

## Solution

**Fully automated pipeline** that:

- Scrapes real-time standings from Codeforces
- Aggregates performance across multiple contests
- Automatically marks participants `Yes`/`No` based on weighted thresholds
- Updates Google Sheets with zero human intervention
- Generates comprehensive analytics reports
- Saves 4-5 hours per automation run
- Eliminates human error completely

---

## Features

### 1. Web Scraping for Private Contests

- Scrapes private Codeforces group contests (no API access needed)
- Bypasses Cloudflare protection using undetected-chromedriver
- Handles pagination automatically
- Extracts participant handles and solved problems
- Includes unofficial/practice-mode participants (configurable)
- Robust error handling and retry logic

### 2. Multi-Contest Weighted Aggregation

- Tracks performance across any number of contests
- Per-contest weight: solving `m` problems is worth `m * weight`
- Weighted score compared against a threshold per sheet/day
- Comprehensive scoring system

### 3. Google Sheets Integration

- OAuth 2.0 authentication
- Accepts a full Google Sheet link (or bare spreadsheet ID)
- Writes `Yes`/`No` in column D based on the weighted score
- Never deletes participant rows
- Professional cell formatting
- Multi-sheet support with per-day thresholds

### 4. Analytics & Reporting

- Combined CSV with all contest data
- Per-contest breakdown
- Total performance metrics
- Easy-to-read summary reports

---

## Installation

### Prerequisites

- Python 3.11+
- Google Cloud Project with Sheets API enabled
- Chrome/Chromium browser

### Setup Steps

1. **Clone the repository**

```bash
git clone https://github.com/omarwael27/Codeforces-private-Contest-data-scraping.git
cd Codeforces-private-Contest-data-scraping
```

2. **Create virtual environment**

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**

```bash
pip install -r requirements.txt
```

4. **Configure Google Sheets API**

   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project
   - Enable Google Sheets API
   - Create OAuth 2.0 credentials
   - Download `credentials.json` to project root

5. **Set up environment variables**

Create a `.env` file in the project root with the following variables:

```env
# Google Sheets Configuration
GOOGLE_SHEET_LINK=https://docs.google.com/spreadsheets/d/your_spreadsheet_id/edit
SHEET_NAMES=Sat 4 -> 8,Sun 10 -> 2,Sun 4 -> 8,Mon 4 -> 8
TOKEN_FILE=token.pickle
CREDENTIALS_FILE=credentials.json

# Performance Thresholds (per sheet/day)
SHEET_THRESHOLDS=Sat 4 -> 8=8;Sun 10 -> 2=10;Sun 4 -> 8=8;Mon 4 -> 8=8
GLOBAL_THRESHOLD=8

# Contests: name|standings_url|weight
CONTEST_COUNT=2
CONTESTS=Contest1|https://.../standings|1;Contest2|https://.../standings|2

# Scraper Settings
RUN_SCRAPER=True
INCLUDE_UNOFFICIAL=True
CHROME_PROFILE_DIR=chrome_profile
LOGIN_TIMEOUT=300

# Output Files
COMBINED_CSV=combined_results.csv
```

6. **Configure contests** (in `.env`)

```env
# Solving m problems in a contest gives m * weight points.
CONTESTS=Contest1|https://.../standings|1;Contest2|https://.../standings|2
```

7. **Log in to Codeforces once**

Private group standings require a logged-in group member. Run:

```bash
python login.py
```

Log in in the opened browser. The session is saved in `chrome_profile/`, so
later runs can access the standings.

---

## Project Structure

```
Codeforces-private-Contest-data-scraping/
├── README.md
├── LICENSE
├── .env.example
├── .gitignore
├── requirements.txt
├── config.py
├── main.py
├── login.py
├── chrome_profile/
├── Contest1_standings.csv
├── Contest2_standings.csv
├── combined_results.csv
├── acm_tracker.log
├── scraper/
│   ├── __init__.py
│   ├── driver.py
│   └── codeforces.py
├── sheets/
│   ├── __init__.py
│   ├── auth.py
│   └── operations.py
└── utils/
    ├── __init__.py
    └── logger.py
```

### Directory Descriptions

- `scraper/` - Web scraping functionality

  - `driver.py` - WebDriver management and configuration
  - `codeforces.py` - Codeforces scraper implementation

- `sheets/` - Google Sheets integration

  - `auth.py` - OAuth 2.0 authentication
  - `operations.py` - Sheet operations (CRUD)

- `utils/` - Utility modules
  - `logger.py` - Logging configuration

---

## Workflow

The system operates in three main phases:

**Scraping Phase**: Retrieves standings from all configured Codeforces contests

**Scoring Phase**: Multiplies each contest's solved count by its weight, then sums the weighted scores

**Google Sheets Update**: Writes `Yes`/`No` in column D for each participant and each sheet/day threshold

**Report Generation**: Creates combined analytics CSV with weighted aggregate results

### Output Files

- `Contest1_standings.csv` - Individual contest results
- `Contest2_standings.csv` - Individual contest results
- `combined_results.csv` - Aggregated results with per-contest weighted scores and weighted totals
- `acm_tracker.log` - Detailed execution log

---

## Configuration

### Environment Variables (`.env`)

| Variable            | Description                                                       | Default  |
| ------------------- | ----------------------------------------------------------------- | -------- |
| `GOOGLE_SHEET_LINK` | Full Google Sheet link (or use `SPREADSHEET_ID`)                  | Required |
| `SPREADSHEET_ID`    | Bare Google Sheets ID (alternative to `GOOGLE_SHEET_LINK`)        | -        |
| `SHEET_NAMES`       | Comma-separated sheet/tab names                                   | Required |
| `SHEET_THRESHOLDS`  | Semicolon-separated `sheet=threshold` pairs                       | -        |
| `GLOBAL_THRESHOLD`  | Fallback threshold for sheets without their own value             | 8        |
| `CONTEST_COUNT`     | Number of contests (must match the `CONTESTS` entries)            | -        |
| `CONTESTS`          | Semicolon-separated `name\|standings_url\|weight` entries         | -        |
| `RUN_SCRAPER`       | Run scraper or load existing CSVs                                 | True     |
| `INCLUDE_UNOFFICIAL`| Count unofficial/practice-mode participants                       | True     |
| `CHROME_VERSION`    | Force ChromeDriver major version (auto-detected if unset)         | -        |
| `CHROME_PROFILE_DIR`| Chrome profile folder that keeps the Codeforces login              | `chrome_profile` |
| `LOGIN_TIMEOUT`     | Seconds `login.py` waits for manual login                         | 300      |

### Contest Configuration (`.env`)

```env
# name|standings_url|weight
CONTESTS=Contest1|https://.../standings|1;Contest2|https://.../standings|2
```

If `CONTESTS` is not set, the values in `config.py` are used.

### Threshold Logic

The weighted score for a participant is:

```
score = sum(solved_in_contest_i * weight_i)
```

A participant is valid to a given sheet/day when `score >= threshold` for that
sheet. The app writes `Yes` in column D when valid and `No` otherwise. Rows are
never deleted, and each sheet can have a different threshold.

---

## Security Notes

**Never commit these files:**

- `credentials.json` - Google API credentials
- `token.pickle` - Authentication token
- `.env` - Environment variables

These are already in `.gitignore` for your protection.

---

## Impact Metrics

| Metric            | Before Automation | After Automation |
| ----------------- | ----------------- | ---------------- |
| Time per cycle    | 4-5 hours         | 5-10 minutes     |
| People required   | 30+ mentors       | 0                |
| Human errors      | Frequent          | Zero             |
| Data accuracy     | ~85-90%           | 100%             |
| Annual time saved | -                 | 200+ hours       |

---

## Troubleshooting

### Common Issues

**1. "Cloudflare blocked access"**

Solution: The scraper waits 15 seconds for Cloudflare challenges. If persistent, increase `CLOUDFLARE_WAIT` in `config.py`.

**2. "credentials.json not found"**

Solution: Download OAuth credentials from Google Cloud Console.

**3. "GOOGLE_SHEET_LINK not set"**

Solution: Add your Google Sheet link to the `.env` file.

**4. Rate limiting**

Solution: Random delays are built in; adjust delays in `config.py`.

**5. "Standings are not available"**

Solution: Private group standings require a logged-in group member. Run
`python login.py`, log in in the opened browser, then run `python main.py`.

---

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## Author

**Omar Wael Mohamed**

- GitHub: [@omarwael27](https://github.com/omarwael27)
- LinkedIn: [omar wael](https://linkedin.com/in/omar-wael-b30a86364/)
- Email: owael2207@gmail.com

---

## Acknowledgments

- Built for acmASCIS Student Chapter at Ain Shams University
- Saves countless hours on data aggregation

---

## Tech Stack

- Python 3.11+ - Core language
- Selenium + undetected-chromedriver - Web scraping
- pandas - Data processing
- Google Sheets API - Spreadsheet automation
- OAuth 2.0 - Secure authentication

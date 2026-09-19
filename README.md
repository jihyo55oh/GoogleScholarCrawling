# Google Scholar Crawler

A semi-autonomous Google Scholar crawler that collects paper metadata and attempts to download multiple formats for each result.

## What it collects

- Paper metadata from Google Scholar
- PDF files
- Plain text extracted from PDFs
- Publisher HTML pages
- PubMed Central XML when available
- DOI metadata through Semantic Scholar
- Open-access PDF links through Unpaywall

Generated files are saved under `output/`.

## Setup

Python 3.9 or newer is recommended.

### macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

### Windows PowerShell

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## Configure a crawl

Edit `START_URL` in `scholar_crawl.py`. You can paste a Google Scholar search URL without adding a `start` parameter:

```python
START_URL = (
    "https://scholar.google.com/scholar"
    "?hl=en&as_sdt=0%2C44&q=shape+memory+alloys&btnG="
)
```

Set the page range with:

```python
START_PAGE = 1
END_PAGE = None
```

`END_PAGE = None` continues until Google Scholar reports no more results or the estimated result count is reached. For a fixed range, use a value such as `END_PAGE = 5`.

## Run

```bash
python scholar_crawl.py
```

The crawler opens a visible Chromium window. Log in to Google Scholar or your institution if needed, solve any CAPTCHA, then return to the terminal and press Enter.

## Output

```text
output/
├── papers.json
├── papers.csv
├── pdfs/
├── texts/
├── html/
└── xml/
```

The `output/` directory is ignored by Git because it contains generated crawl results, which can be large and vary between runs.

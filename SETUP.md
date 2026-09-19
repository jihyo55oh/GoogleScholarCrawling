# Setup

The crawler requires Python 3.9 or newer.

## macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
python scholar_crawl.py
```

## Windows PowerShell

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
python scholar_crawl.py
```

The `requirements.txt` file installs the Python libraries. The Playwright command
installs the Chromium browser used by the crawler and is required once per laptop.

import os, json, random, urllib.request, urllib.error
from pathlib import Path
from html.parser import HTMLParser

API_KEY = os.environ.get("GEMINI_API_KEY", "")
if not API_KEY:
    API_KEY = input("Paste your Gemini API key: ").strip()

MODEL = "gemini-2.5-flash"

# ── pick a random HTML file ───────────────────────────────────────────────────
html_dir = Path("output/html")
html_files = list(html_dir.glob("*.html"))
chosen = random.choice(html_files)
print(f"Chosen file: {chosen.name}\n")

# ── strip tags to plain text ──────────────────────────────────────────────────
class _Stripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip = False
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "header", "footer"):
            self._skip = True
    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "header", "footer"):
            self._skip = False
    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip())

stripper = _Stripper()
stripper.feed(chosen.read_text(encoding="utf-8", errors="ignore"))
plain_text = "\n".join(stripper.parts)[:12000]   # cap at ~12k chars

# ── call Gemini ───────────────────────────────────────────────────────────────
prompt = (
    "Summarize the following academic paper in 3-5 sentences. "
    "Focus on: what materials were studied, what properties were measured, "
    "and the key findings.\n\n" + plain_text
)

url = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{MODEL}:generateContent?key={API_KEY}"
)
body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
req = urllib.request.Request(url, data=body,
                              headers={"Content-Type": "application/json"}, method="POST")

with urllib.request.urlopen(req, timeout=30) as resp:
    data = json.loads(resp.read())

summary = data["candidates"][0]["content"]["parts"][0]["text"].strip()

# ── save ──────────────────────────────────────────────────────────────────────
out = Path("test.txt")
out.write_text(f"Source: {chosen.name}\n\n{summary}\n", encoding="utf-8")
print(summary)
print(f"\nSaved to {out}")

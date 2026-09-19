"""
Quick test script for a Gemini API key.
Tries current free-tier models in order and reports which ones work.

Usage:
    python3 test_gemini.py
    # or set the key inline:
    GEMINI_API_KEY=your_key python3 test_gemini.py
"""

import os
import urllib.request
import urllib.error
import json

API_KEY = os.environ.get("GEMINI_API_KEY", "")

if not API_KEY:
    API_KEY = input("Paste your Gemini API key: ").strip()

MODELS_TO_TRY = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
]

PROMPT = "Reply with exactly: API key works."

def test_model(model: str) -> tuple[bool, str]:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={API_KEY}"
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": PROMPT}]}]
    }).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            return True, text
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="ignore")
        try:
            msg = json.loads(msg).get("error", {}).get("message", msg)
        except Exception:
            pass
        return False, msg
    except Exception as e:
        return False, str(e)


print(f"\nTesting {len(MODELS_TO_TRY)} Gemini models...\n")
working = []

for model in MODELS_TO_TRY:
    ok, result = test_model(model)
    status = "OK " if ok else "FAIL"
    print(f"  [{status}] {model}")
    if ok:
        print(f"         → \"{result}\"")
        working.append(model)
    else:
        print(f"         → {result[:120]}")

print()
if working:
    print(f"Use this model in your scripts: \"{working[0]}\"")
else:
    print("No models worked. Double-check the API key and that your Google account has Gemini API access.")
    print("Get a key at: https://aistudio.google.com/app/apikey")

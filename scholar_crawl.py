"""
Google Scholar cited-by crawler — multi-format downloader.

Per paper, attempts to collect:
  - PDF  (Scholar [PDF] link → Unpaywall open-access → publisher page)
  - TXT  (extracted from PDF via pymupdf)
  - HTML (publisher full-text page via Playwright browser session)
  - XML  (PubMed Central, when the paper is indexed there)

Saves metadata to output/papers.json and output/papers.csv.
"""

import asyncio
import json
import re
import time
import unicodedata
from pathlib import Path

import fitz  # pymupdf
import pandas as pd
import requests
from playwright.async_api import async_playwright

START_URL = (
    "https://scholar.google.com/scholar"
    "?hl=en&as_sdt=0%2C44&q=shape+memory+alloys&btnG="
)

# Page numbers are one-based. Set END_PAGE to None to crawl until Scholar
# stops returning results (or until Scholar's estimated result count is reached).
START_PAGE = 1
END_PAGE = None

OUTPUT_DIR = Path("output")
DIRS = {
    "pdf":  OUTPUT_DIR / "pdfs",
    "txt":  OUTPUT_DIR / "texts",
    "html": OUTPUT_DIR / "html",
    "xml":  OUTPUT_DIR / "xml",
}
for d in DIRS.values():
    d.mkdir(parents=True, exist_ok=True)

RESULTS_PER_PAGE = 10
PAGE_DELAY = 4          # seconds between Scholar pages
DOWNLOAD_DELAY = 2      # seconds between per-paper downloads

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; research-crawler/1.0)"}


# ── Filename helpers ──────────────────────────────────────────────────────────

def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:max_len]


def stem(paper: dict) -> str:
    author = slugify(paper.get("authors", "unknown").split(",")[0].split()[-1])
    year   = paper.get("year", "0000")
    title  = slugify(paper.get("title", "untitled"))
    return f"{author}_{year}_{title}"


# ── Scholar scraping ──────────────────────────────────────────────────────────

async def scrape_page(page) -> list[dict]:
    await page.wait_for_selector("#gs_res_ccl", timeout=15000)
    return await page.evaluate("""() => {
        const papers = [];
        document.querySelectorAll('.gs_r.gs_or.gs_scl').forEach(el => {
            const titleEl = el.querySelector('.gs_rt a');
            const title    = titleEl ? titleEl.innerText.trim() : '';
            const link     = titleEl ? titleEl.href : '';

            // [PDF] link shown in Scholar sidebar
            const pdfEl   = el.querySelector('.gs_or_ggsm a, .gs_ggsd a');
            const pdf_link = pdfEl ? pdfEl.href : '';

            const metaEl = el.querySelector('.gs_a');
            const meta   = metaEl ? metaEl.innerText.trim() : '';
            const yearMatch = meta.match(/\\b(19|20)\\d{2}\\b/);
            const year   = yearMatch ? yearMatch[0] : '';
            const parts  = meta.split(' - ');
            const authors = parts[0] ? parts[0].trim() : '';
            const venue   = parts[1] ? parts[1].trim() : '';

            const absEl   = el.querySelector('.gs_rs');
            const abstract = absEl ? absEl.innerText.trim() : '';

            papers.push({ title, link, pdf_link, authors, venue, year, abstract });
        });
        return papers;
    }""")


async def get_total_pages(page) -> int:
    try:
        text = await page.inner_text("#gs_ab_md")
        m = re.search(r"About ([\d,]+) results", text)
        if m:
            total = int(m.group(1).replace(",", ""))
            return (total // RESULTS_PER_PAGE) + 1
    except Exception:
        pass
    return 30


# ── DOI / metadata enrichment ─────────────────────────────────────────────────

def lookup_doi(title: str, authors: str) -> str:
    """Query Semantic Scholar for DOI by title."""
    try:
        first_author = authors.split(",")[0].split()[-1] if authors else ""
        r = requests.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={"query": f"{title} {first_author}", "fields": "externalIds,title", "limit": 1},
            headers=HEADERS, timeout=10,
        )
        r.raise_for_status()
        items = r.json().get("data", [])
        if items:
            ids = items[0].get("externalIds", {})
            return ids.get("DOI", "")
    except Exception:
        pass
    return ""


def unpaywall_pdf(doi: str) -> str:
    """Return open-access PDF URL via Unpaywall, or empty string."""
    if not doi:
        return ""
    try:
        r = requests.get(
            f"https://api.unpaywall.org/v2/{doi}",
            params={"email": "research@example.com"},
            headers=HEADERS, timeout=10,
        )
        r.raise_for_status()
        data = r.json()
            # best_oa_location is the recommended field
        loc = data.get("best_oa_location") or {}
        return loc.get("url_for_pdf") or loc.get("url") or ""
    except Exception:
        return ""


def pmc_id(doi: str) -> str:
    """Return PubMed Central ID for a DOI, or empty string."""
    if not doi:
        return ""
    try:
        r = requests.get(
            "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
            params={"ids": doi, "format": "json"},
            headers=HEADERS, timeout=10,
        )
        r.raise_for_status()
        records = r.json().get("records", [])
        return records[0].get("pmcid", "") if records else ""
    except Exception:
        return ""


# ── Format downloaders ────────────────────────────────────────────────────────

def download_pdf_requests(url: str, dest: Path) -> bool:
    """Download a PDF via plain requests (for open-access URLs)."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        ct = r.headers.get("Content-Type", "")
        if "pdf" in ct or url.lower().endswith(".pdf"):
            dest.write_bytes(r.content)
            return True
    except Exception:
        pass
    return False


async def download_pdf_browser(browser_page, url: str, dest: Path) -> bool:
    """Download a PDF using the Playwright browser session (uses institutional cookies)."""
    try:
        tab = await browser_page.context.new_page()
        await tab.goto(url, timeout=25000, wait_until="domcontentloaded")
        ct = await tab.evaluate("document.contentType")
        if "pdf" in ct:
            pdf_bytes = await tab.evaluate("""async () => {
                const r = await fetch(window.location.href);
                const buf = await r.arrayBuffer();
                return Array.from(new Uint8Array(buf));
            }""")
            dest.write_bytes(bytes(pdf_bytes))
            await tab.close()
            return True
        await tab.close()
    except Exception:
        pass
    return False


def extract_txt(pdf_path: Path, txt_path: Path) -> bool:
    """Extract plain text from a PDF using pymupdf."""
    try:
        doc = fitz.open(str(pdf_path))
        text = "\n\n".join(page.get_text() for page in doc)
        doc.close()
        if text.strip():
            txt_path.write_text(text, encoding="utf-8")
            return True
    except Exception:
        pass
    return False


async def download_html(browser_page, url: str, dest: Path) -> bool:
    """Fetch publisher full-text HTML via the browser session."""
    if not url:
        return False
    try:
        tab = await browser_page.context.new_page()
        await tab.goto(url, timeout=25000, wait_until="domcontentloaded")
        html = await tab.content()
        dest.write_text(html, encoding="utf-8")
        await tab.close()
        return True
    except Exception:
        pass
    return False


def download_pmc_xml(pmcid: str, dest: Path) -> bool:
    """Download full-text XML from PubMed Central."""
    if not pmcid:
        return False
    try:
        url = f"https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_xml/{pmcid}/unicode"
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.ok and "<document>" in r.text:
            dest.write_text(r.text, encoding="utf-8")
            return True
    except Exception:
        pass
    return False


# ── Persistence ───────────────────────────────────────────────────────────────

def save_results(papers: list[dict]):
    (OUTPUT_DIR / "papers.json").write_text(
        json.dumps(papers, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    pd.DataFrame(papers).to_csv(OUTPUT_DIR / "papers.csv", index=False)


def scholar_page_url(base_url: str, page_number: int) -> str:
    """Add or replace Scholar's zero-based start offset in a pasted URL."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["start"] = str((page_number - 1) * RESULTS_PER_PAGE)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    all_papers = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, slow_mo=80)
        context = await browser.new_context(accept_downloads=True)
        scholar_page = await context.new_page()

        print("Opening Scholar. Log in to your institution in the browser if prompted.")
        print("Solve any CAPTCHA that appears, then come back here.\n")
        await scholar_page.goto(scholar_page_url(START_URL, START_PAGE), timeout=30000)
        input("Press ENTER once the Scholar results are visible in the browser... ")

        estimated_pages = await get_total_pages(scholar_page)
        last_page = END_PAGE or estimated_pages
        print(
            f"Pages to scrape: {START_PAGE}–{last_page} "
            f"({'automatic end' if END_PAGE is None else 'configured end'})\n"
        )

        # ── Phase 1: collect metadata ─────────────────────────────────────────
        for page_num in range(START_PAGE, last_page + 1):
            url = scholar_page_url(START_URL, page_num)

            if page_num > START_PAGE:
                print(f"Page {page_num} / {last_page}")
                await scholar_page.goto(url, timeout=30000)
                await asyncio.sleep(PAGE_DELAY)

            if await scholar_page.query_selector("#gs_captcha_ccl, #recaptcha"):
                input(f"  CAPTCHA on page {page_num} — solve it, then press ENTER... ")

            papers = await scrape_page(scholar_page)
            if not papers:
                print(f"  No results on page {page_num}, stopping.")
                break

            print(f"  {len(papers)} papers found (start={(page_num - 1) * RESULTS_PER_PAGE})")
            all_papers.extend(papers)
            save_results(all_papers)

        print(f"\nMetadata done. {len(all_papers)} papers total.\n")

        # ── Phase 2: enrich + download per paper ─────────────────────────────
        dl_page = await context.new_page()

        for i, paper in enumerate(all_papers):
            name = stem(paper)
            print(f"\n[{i+1}/{len(all_papers)}] {paper['title'][:70]}")

            # Enrich with DOI
            if not paper.get("doi"):
                paper["doi"] = lookup_doi(paper["title"], paper.get("authors", ""))
            doi = paper["doi"]
            if doi:
                print(f"  DOI: {doi}")

            # ── PDF ──────────────────────────────────────────────────────────
            pdf_path = DIRS["pdf"] / f"{name}.pdf"
            got_pdf = pdf_path.exists()

            if not got_pdf:
                # 1. Scholar [PDF] link
                if paper.get("pdf_link"):
                    print("  PDF: trying Scholar link...")
                    got_pdf = await download_pdf_browser(dl_page, paper["pdf_link"], pdf_path)

                # 2. Unpaywall open-access
                if not got_pdf and doi:
                    oa_url = unpaywall_pdf(doi)
                    if oa_url:
                        print("  PDF: trying Unpaywall open-access...")
                        got_pdf = download_pdf_requests(oa_url, pdf_path)

                # 3. Publisher page via browser (institutional access)
                if not got_pdf and paper.get("link"):
                    print("  PDF: trying publisher page via browser...")
                    got_pdf = await download_pdf_browser(dl_page, paper["link"], pdf_path)

            paper["pdf_saved"] = got_pdf
            print(f"  PDF: {'ok' if got_pdf else 'not available'}")

            # ── TXT (extracted from PDF) ──────────────────────────────────────
            txt_path = DIRS["txt"] / f"{name}.txt"
            got_txt = txt_path.exists()
            if not got_txt and got_pdf:
                got_txt = extract_txt(pdf_path, txt_path)
            paper["txt_saved"] = got_txt
            if got_txt:
                print(f"  TXT: extracted")

            # ── HTML (publisher full-text page) ──────────────────────────────
            html_path = DIRS["html"] / f"{name}.html"
            got_html = html_path.exists()
            if not got_html and paper.get("link"):
                print("  HTML: fetching publisher page...")
                got_html = await download_html(dl_page, paper["link"], html_path)
            paper["html_saved"] = got_html
            print(f"  HTML: {'ok' if got_html else 'not available'}")

            # ── XML (PubMed Central) ──────────────────────────────────────────
            xml_path = DIRS["xml"] / f"{name}.xml"
            got_xml = xml_path.exists()
            if not got_xml:
                pmcid = pmc_id(doi)
                if pmcid:
                    print(f"  XML: PMC {pmcid}...")
                    got_xml = download_pmc_xml(pmcid, xml_path)
            paper["xml_saved"] = got_xml
            if got_xml:
                print(f"  XML: ok")

            save_results(all_papers)
            await asyncio.sleep(DOWNLOAD_DELAY)

        await browser.close()

    # ── Summary ───────────────────────────────────────────────────────────────
    df = pd.DataFrame(all_papers)
    print("\n=== Download summary ===")
    for fmt in ("pdf", "txt", "html", "xml"):
        col = f"{fmt}_saved"
        if col in df.columns:
            n = df[col].sum()
            print(f"  {fmt.upper():4s}: {n}/{len(df)}")
    print(f"\nOutputs saved to {OUTPUT_DIR}/")


if __name__ == "__main__":
    asyncio.run(main())

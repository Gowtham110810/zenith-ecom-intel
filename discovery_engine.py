import urllib.parse
import requests
from bs4 import BeautifulSoup
import central_core

try:
    from duckduckgo_search import DDGS
except ImportError:
    DDGS = None

DIRECTORY_BLACKLIST = {
    "amazon.in", "amazon.com", "flipkart.com", "myntra.com", "nykaa.com", "ajio.com",
    "meesho.com", "indiamart.com", "justdial.com", "facebook.com", "instagram.com",
    "linkedin.com", "youtube.com", "wikipedia.org", "google.com", "yahoo.com", "bing.com"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}


def generate_smart_queries(category, city):
    prompt = f"""
    I need to find official standalone D2C e-commerce and Shopify online stores selling '{category}' in '{city}' or India.
    Generate 3 specific search queries that return independent online brand stores and filter out marketplaces like Amazon or Flipkart.
    Output ONLY the 3 queries, one per line.
    """
    response = central_core.call_gemini(prompt)
    queries = []
    if response and "Error" not in response:
        for line in response.split("\n"):
            clean = line.strip().strip("-").strip('"').strip("'")
            if len(clean) > 5:
                queries.append(clean)

    if len(queries) < 2:
        queries = [
            f'{category} online store {city} "contact" -amazon -flipkart',
            f'buy {category} India D2C brand official website -amazon -flipkart',
            f'{category} shopify store India email address'
        ]
    return queries[:3]


def scrape_yahoo(query):
    urls = []
    try:
        url = f"https://search.yahoo.com/search?p={urllib.parse.quote(query)}"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("http") and "yahoo.com" not in href:
                urls.append(href)
    except Exception:
        pass
    return urls


def deep_discover_urls(category, city):
    queries = generate_smart_queries(category, city)
    candidates = set()

    if DDGS:
        try:
            ddgs = DDGS()
            for q in queries:
                for r in ddgs.text(q, max_results=12):
                    if r.get("href"):
                        candidates.add(r["href"])
        except Exception:
            pass

    for q in queries:
        for u in scrape_yahoo(q):
            candidates.add(u)

    final_urls = []
    seen_domains = set()
    for url in candidates:
        if not url.startswith("http"):
            continue
        try:
            netloc = urllib.parse.urlparse(url).netloc.lower().replace("www.", "")
            if not netloc or "." not in netloc:
                continue
            if any(b in netloc for b in DIRECTORY_BLACKLIST):
                continue
            if netloc not in seen_domains:
                seen_domains.add(netloc)
                final_urls.append(url)
        except Exception:
            continue

    return final_urls

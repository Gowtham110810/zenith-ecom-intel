import os
import re
import json
import sqlite3
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup
import central_core

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9"
}


def get_telegram_credentials():
    """Fetches Telegram Bot Token & Chat ID from Streamlit Secrets, Env, or SQLite."""
    central_core.init_databases()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    try:
        import streamlit as st
        if not token:
            token = st.secrets.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not chat_id:
            chat_id = str(st.secrets.get("TELEGRAM_CHAT_ID", "")).strip()
    except Exception:
        pass

    conn = sqlite3.connect(central_core.ECOM_DB)
    cur = conn.cursor()
    if not token:
        cur.execute("SELECT value FROM settings WHERE key = 'telegram_token'")
        row = cur.fetchone()
        if row:
            token = row[0]
    if not chat_id:
        cur.execute("SELECT value FROM settings WHERE key = 'telegram_chat_id'")
        row = cur.fetchone()
        if row:
            chat_id = row[0]
    conn.close()
    return token, chat_id


def save_telegram_credentials(token, chat_id):
    central_core.init_databases()
    conn = sqlite3.connect(central_core.ECOM_DB)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('telegram_token', ?)", (token.strip(),))
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('telegram_chat_id', ?)", (str(chat_id).strip(),))
    conn.commit()
    conn.close()


def auto_detect_chat_id(token):
    """Automatically grabs your Chat ID from the latest message sent to your bot."""
    try:
        url = f"https://api.telegram.org/bot{token.strip()}/getUpdates"
        resp = requests.get(url, timeout=10).json()
        if resp.get("ok") and resp.get("result"):
            for item in reversed(resp["result"]):
                msg = item.get("message") or item.get("channel_post") or {}
                chat = msg.get("chat", {})
                if "id" in chat:
                    return str(chat["id"]), "Successfully detected Chat ID!"
        return "", "No messages found. Open Telegram, send 'Hello' to your bot first, then click Detect again."
    except Exception as e:
        return "", f"Error contacting Telegram API: {str(e)}"


def send_telegram_alert(message):
    """Sends a formatted alert message to Telegram."""
    token, chat_id = get_telegram_credentials()
    if not token or not chat_id:
        return False, "Telegram Token or Chat ID is missing."
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": False}
        resp = requests.post(url, json=payload, timeout=10).json()
        if resp.get("ok"):
            return True, "Telegram alert sent!"
        return False, f"Telegram API Error: {resp.get('description', 'Unknown error')}"
    except Exception as e:
        return False, str(e)


def parse_price_number(raw_val):
    if raw_val is None:
        return None
    cleaned = re.sub(r"[^\d.]", "", str(raw_val).replace(",", ""))
    try:
        val = float(cleaned)
        return val if val > 0 else None
    except Exception:
        return None


def scrape_product_data(url):
    """
    3-Layer E-Commerce Extractor:
    Layer 1: Shopify .json endpoint
    Layer 2: Schema.org application/ld+json
    Layer 3: HTML + Regex / Meta tags
    """
    clean_url = url.split("?")[0].rstrip("/")

    # Layer 1: Try Shopify JSON API (Works on 90% of D2C brands)
    if "/products/" in clean_url:
        try:
            r_json = requests.get(f"{clean_url}.json", headers=HEADERS, timeout=8)
            if r_json.status_code == 200 and "product" in r_json.json():
                prod = r_json.json()["product"]
                title = prod.get("title", "Tracked Product")
                variants = prod.get("variants", [])
                if variants:
                    price = parse_price_number(variants[0].get("price"))
                    in_stock = any(v.get("available", True) for v in variants)
                    if price:
                        return {"title": title, "price": price, "in_stock": in_stock}
        except Exception:
            pass

    # Fetch standard HTML page
    resp = requests.get(url, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(resp.text, "html.parser")
    title = soup.find("title").get_text(strip=True)[:80] if soup.find("title") else clean_url

    # Layer 2: Schema.org JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") == "Product" or "offers" in item:
                    title = item.get("name", title)
                    offers = item.get("offers", {})
                    if isinstance(offers, list) and offers:
                        offers = offers[0]
                    price = parse_price_number(offers.get("price") or offers.get("lowPrice"))
                    avail = str(offers.get("availability", "InStock")).lower()
                    in_stock = "outofstock" not in avail and "soldout" not in avail
                    if price:
                        return {"title": title, "price": price, "in_stock": in_stock}
        except Exception:
            continue

    # Layer 3: Meta tags & visible ₹ / Rs. price regex
    meta_price = (
        soup.find("meta", property="product:price:amount")
        or soup.find("meta", property="og:price:amount")
    )
    if meta_price and meta_price.get("content"):
        price = parse_price_number(meta_price["content"])
        if price:
            html_low = resp.text.lower()
            in_stock = "out of stock" not in html_low and "sold out" not in html_low
            return {"title": title, "price": price, "in_stock": in_stock}

    text_content = soup.get_text(" ", strip=True)
    matches = re.findall(r"(?:₹|Rs\.?|INR)\s*([\d,]+(?:\.\d{1,2})?)", text_content)
    for m in matches:
        price = parse_price_number(m)
        if price and 10 <= price <= 500000:
            in_stock = "out of stock" not in text_content.lower()
            return {"title": title, "price": price, "in_stock": in_stock}

    return None


def add_or_check_product(url, notify_on_add=True):
    """Adds a product or checks an existing product for price/stock changes."""
    central_core.init_databases()
    data = scrape_product_data(url)
    if not data:
        return False, "Could not extract a valid price from that URL. Try a direct product page."

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    conn = sqlite3.connect(central_core.ECOM_DB)
    cur = conn.cursor()

    cur.execute("SELECT id, product_name, last_price, in_stock FROM products WHERE url = ?", (url,))
    existing = cur.fetchone()

    alert_msg = None
    if not existing:
        cur.execute(
            "INSERT INTO products (product_name, url, last_price, in_stock, last_checked) VALUES (?, ?, ?, ?, ?)",
            (data["title"], url, data["price"], int(data["in_stock"]), now_str)
        )
        prod_id = cur.lastrowid
        if notify_on_add:
            stock_label = "In Stock ✅" if data["in_stock"] else "Out of Stock ❌"
            alert_msg = (
                f"🛰️ <b>New Competitor Product Tracked!</b>\n\n"
                f"<b>Product:</b> {data['title']}\n"
                f"<b>Current Price:</b> ₹{data['price']:,.2f}\n"
                f"<b>Status:</b> {stock_label}\n"
                f"<a href='{url}'>View Product Page</a>"
            )
    else:
        prod_id, old_name, old_price, old_stock = existing
        old_stock_bool = bool(old_stock)
        new_price = data["price"]
        new_stock_bool = data["in_stock"]

        if new_price < old_price:
            diff = old_price - new_price
            alert_msg = (
                f"🚨 <b>PRICE DROP ALERT!</b>\n\n"
                f"<b>Product:</b> {old_name}\n"
                f"<b>Old Price:</b> ₹{old_price:,.2f}\n"
                f"<b>New Price:</b> ₹{new_price:,.2f} (Dropped by ₹{diff:,.2f}!)\n"
                f"<a href='{url}'>View Competitor Page</a>"
            )
        elif new_price > old_price:
            diff = new_price - old_price
            alert_msg = (
                f"📈 <b>COMPETITOR PRICE INCREASE!</b>\n\n"
                f"<b>Product:</b> {old_name}\n"
                f"<b>Old Price:</b> ₹{old_price:,.2f}\n"
                f"<b>New Price:</b> ₹{new_price:,.2f} (+₹{diff:,.2f})\n"
                f"<a href='{url}'>View Competitor Page</a>"
            )
        elif old_stock_bool and not new_stock_bool:
            alert_msg = (
                f"⚠️ <b>COMPETITOR OUT OF STOCK!</b>\n\n"
                f"<b>Product:</b> {old_name} just ran out of stock at ₹{new_price:,.2f}!\n"
                f"<a href='{url}'>View Competitor Page</a>"
            )

        cur.execute(
            "UPDATE products SET last_price = ?, in_stock = ?, last_checked = ? WHERE id = ?",
            (new_price, int(new_stock_bool), now_str, prod_id)
        )

    cur.execute(
        "INSERT INTO price_history (product_id, price, in_stock, checked_at) VALUES (?, ?, ?, ?)",
        (prod_id, data["price"], int(data["in_stock"]), now_str)
    )
    conn.commit()
    conn.close()

    if alert_msg:
        send_telegram_alert(alert_msg)

    return True, f"Tracked '{data['title']}' at ₹{data['price']:,.2f}"


def check_all_tracked_products():
    """Scans every product in the database and triggers alerts if prices changed."""
    central_core.init_databases()
    conn = sqlite3.connect(central_core.ECOM_DB)
    cur = conn.cursor()
    cur.execute("SELECT url FROM products")
    urls = [r[0] for r in cur.fetchall()]
    conn.close()

    checked = 0
    for u in urls:
        ok, _ = add_or_check_product(u, notify_on_add=False)
        if ok:
            checked += 1
    return checked

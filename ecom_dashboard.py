import sqlite3
import urllib.parse
import pandas as pd
import streamlit as st
import central_core
import price_tracker
import ecom_lead_hunter

st.set_page_config(page_title="Zenith E-Com Intelligence", page_icon="📈", layout="wide")
central_core.init_databases()

if "ecom_leads" not in st.session_state:
    st.session_state.ecom_leads = []

st.title("📈 Zenith E-Commerce Competitor Price & Stock Spy")
st.caption("Rank 2 B2B SaaS: 24/7 Competitor Price & Inventory Monitoring + Instant Telegram Alerts + D2C Auto-Lead Hunter")

tab1, tab2, tab3 = st.tabs([
    "🛰️ Live Competitor Price Tracker",
    "📲 Telegram Alert Bot Setup",
    "🎯 D2C Store Lead Hunter (5/Day Cap)"
])

# --- TAB 1: COMPETITOR PRICE & STOCK TRACKER ---
with tab1:
    st.subheader("Track Competitor Product URLs (Shopify, WooCommerce & D2C Stores)")
    with st.form("add_product_form"):
        prod_url = st.text_input("Paste Competitor Product Page URL", placeholder="https://competitorstore.com/products/vitamin-c-serum")
        add_btn = st.form_submit_button("➕ Track Product & Send Instant Telegram Confirmation")

    if add_btn and prod_url:
        with st.spinner("Extracting product price, stock status, and triggering Telegram alert..."):
            ok, msg = price_tracker.add_or_check_product(prod_url.strip(), notify_on_add=True)
        if ok:
            st.success(msg)
        else:
            st.error(msg)

    col_check, _ = st.columns([1, 3])
    if col_check.button("🔄 Scan All Tracked Products Now"):
        with st.spinner("Checking all tracked products for price drops or stock changes..."):
            count = price_tracker.check_all_tracked_products()
        st.success(f"Scanned {count} product(s). Any price or stock changes were sent to Telegram!")

    conn = sqlite3.connect(central_core.ECOM_DB)
    df_prods = pd.read_sql_query(
        "SELECT id, product_name, last_price AS price_inr, CASE WHEN in_stock=1 THEN 'In Stock ✅' ELSE 'Out of Stock ❌' END AS status, url, last_checked FROM products ORDER BY id DESC",
        conn
    )
    conn.close()

    if not df_prods.empty:
        st.dataframe(df_prods, use_container_width=True)
    else:
        st.info("No competitor products tracked yet. Paste any D2C product URL above to test!")

# --- TAB 2: TELEGRAM BOT CONFIG & 1-CLICK CHAT ID DETECTOR ---
with tab2:
    st.subheader("Connect Your Telegram Alert Bot in 60 Seconds")
    st.markdown("""
    1. Open Telegram, search for **@BotFather**, and send `/newbot` to get your **Bot Token**.
    2. Open a chat with your new bot in Telegram and send it the word `Hello`.
    3. Paste your token below and click **Auto-Detect Chat ID & Send Test Alert**.
    """)

    saved_token, saved_chat_id = price_tracker.get_telegram_credentials()

    bot_token_input = st.text_input("Telegram Bot Token", value=saved_token, type="password")
    chat_id_input = st.text_input("Telegram Chat ID (Or click Auto-Detect below)", value=saved_chat_id)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("🔍 Auto-Detect Chat ID from Telegram"):
            if not bot_token_input:
                st.error("Paste your Bot Token first!")
            else:
                detected_id, status_msg = price_tracker.auto_detect_chat_id(bot_token_input)
                if detected_id:
                    price_tracker.save_telegram_credentials(bot_token_input, detected_id)
                    st.success(f"{status_msg} (ID: {detected_id})")
                    st.rerun()
                else:
                    st.warning(status_msg)

    with c2:
        if st.button("💾 Save & Send Test Alert to My Phone"):
            price_tracker.save_telegram_credentials(bot_token_input, chat_id_input)
            ok, msg = price_tracker.send_telegram_alert(
                "🚀 <b>Zenith E-Commerce Spy Connected!</b>\nYour phone will now receive instant competitor price drop and stock alerts."
            )
            if ok:
                st.success("✅ Test alert sent! Check your Telegram app.")
            else:
                st.error(msg)

# --- TAB 3: D2C LEAD HUNTER ---
with tab3:
    st.subheader("Discover D2C Brands & Pitch Competitor Intelligence (zenith.ai.gowtham@gmail.com)")

    sent_today = ecom_lead_hunter.get_today_sent_count()
    remaining_quota = max(0, ecom_lead_hunter.DAILY_EMAIL_LIMIT - sent_today)

    m1, m2, m3 = st.columns(3)
    m1.metric("Daily Sending Limit", f"{ecom_lead_hunter.DAILY_EMAIL_LIMIT} Emails / Day")
    m2.metric("Sent Today", sent_today)
    m3.metric("Remaining Quota Today", remaining_quota)

    with st.form("ecom_hunt_form"):
        col1, col2 = st.columns(2)
        category = col1.text_input("D2C Niche / Product Category", value="Skincare & Cosmetics")
        city = col2.text_input("Target City / Region", value="Mumbai")
        hunt_btn = st.form_submit_button("🔍 Step 1: Discover D2C & Shopify Brands")

    if hunt_btn:
        with st.spinner(f"Scanning for standalone {category} stores in {city}..."):
            st.session_state.ecom_leads = ecom_lead_hunter.hunt_ecom_leads(category, city)
        if not st.session_state.ecom_leads:
            st.warning("No uncontacted stores found in that scan. Try another category like 'Fitness Apparel' or 'Specialty Coffee'.")

    leads = st.session_state.ecom_leads
    if leads:
        st.success(f"Found {len(leads)} D2C brand lead(s)!")
        if remaining_quota > 0:
            if st.button(f"⚡ Auto-Send Top {min(len(leads), remaining_quota)} Pitches Now"):
                for idx, lead in enumerate(leads):
                    if ecom_lead_hunter.get_today_sent_count() >= ecom_lead_hunter.DAILY_EMAIL_LIMIT:
                        break
                    target_email = lead["emails"][0]
                    if ecom_lead_hunter.is_already_contacted(target_email):
                        continue
                    subject = f"24/7 Competitor Price & Stock Alerts for {lead['business_name']}"
                    pitch_text = st.session_state.get(f"epitch_{idx}", lead["pitch"])
                    ok, msg = ecom_lead_hunter.send_automated_email(
                        lead["business_name"], lead["url"], target_email, subject, pitch_text
                    )
                    if ok:
                        st.toast(f"✅ Sent to {target_email}")
                    else:
                        st.error(f"❌ {target_email}: {msg}")
                st.rerun()

        for idx, lead in enumerate(leads):
            target_email = lead["emails"][0]
            already_sent = ecom_lead_hunter.is_already_contacted(target_email)
            badge = "✅ SENT" if already_sent else "🟢 READY"
            with st.expander(f"{badge} | #{idx+1}: {lead['business_name']} ({lead['url']})", expanded=(idx < 5 and not already_sent)):
                st.write(f"**Target Email:** `{target_email}`")
                pitch = st.text_area("Pitch:", value=lead["pitch"], height=150, key=f"epitch_{idx}")
                subject = f"24/7 Competitor Price & Stock Alerts for {lead['business_name']}"
                if st.button(f"🚀 Auto-Send via SMTP to {target_email}", key=f"esend_{idx}", disabled=(already_sent or remaining_quota == 0)):
                    ok, msg = ecom_lead_hunter.send_automated_email(
                        lead["business_name"], lead["url"], target_email, subject, pitch
                    )
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

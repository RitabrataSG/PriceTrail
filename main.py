"""Simple price tracker (tracks up to 1000 books automatically).

Usage:
    python main.py collect    # scrape current prices and store them in prices.db
    python main.py analyze    # report price drops and weekday patterns

Running with no command (e.g. the VS Code Run button) does "collect".
"""
import os
import re
import sys
import time
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
import pandas as pd
from bs4 import BeautifulSoup

# Always keep prices.db next to this script, wherever you run it from
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prices.db")
HEADERS = {"User-Agent": "price-tracker-learning-project (contact: you@example.com)"}

# How many products to track. Set 50, 100, 200 ... up to 1000 (the site has 1000 books).
MAX_PRODUCTS = 100

BASE = "https://books.toscrape.com/catalogue/"  # practice site built for scraping


def get_products(limit=MAX_PRODUCTS):
    """Walk the listing pages and return a list of (url, name, price).

    Each listing page shows 20 books with their prices, so 100 products
    needs only 5 page requests instead of 100.
    """
    products = []
    page = 1
    while len(products) < limit:
        page_url = f"{BASE}page-{page}.html"
        r = requests.get(page_url, headers=HEADERS, timeout=20)
        if r.status_code == 404:  # ran out of pages
            break
        r.raise_for_status()
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")

        for card in soup.select("article.product_pod"):
            link = card.select_one("h3 a")
            url = urljoin(page_url, link["href"])
            name = link["title"]
            price_text = card.select_one(".price_color").get_text()
            price = float(re.sub(r"[^0-9.]", "", price_text))
            products.append((url, name, price))

        print(f"page {page}: {len(products)} products so far")
        page += 1
        time.sleep(1)  # be polite

    return products[:limit]


def collect():
    con = sqlite3.connect(DB)
    con.execute(
        "CREATE TABLE IF NOT EXISTS price_snapshots("
        "url TEXT, name TEXT, captured_at TEXT, price REAL)"
    )
    try:
        products = get_products()
    except Exception as e:
        print("failed to fetch products:", e)
        con.close()
        return

    now = datetime.now(timezone.utc).isoformat()
    con.executemany(
        "INSERT INTO price_snapshots VALUES (?,?,?,?)",
        [(url, name, now, price) for url, name, price in products],
    )
    con.commit()
    con.close()

    print(f"\nSaved {len(products)} prices. Data is stored in: {DB}")
    for url, name, price in products[:5]:
        print(f"  {name} -> {price}")
    if len(products) > 5:
        print("  ...")


def analyze():
    if not os.path.exists(DB):
        print("No prices.db yet. Run 'python main.py collect' first.")
        return

    con = sqlite3.connect(DB)
    df = pd.read_sql("SELECT * FROM price_snapshots", con, parse_dates=["captured_at"])
    con.close()

    if df.empty:
        print("No data yet. Run 'python main.py collect' first.")
        return

    df = df.sort_values(["url", "captured_at"])
    g = df.groupby("url")["price"]
    df["pct_change"] = g.pct_change()
    df["high_30d"] = g.transform(lambda s: s.rolling(30, min_periods=1).max())
    df["drop_from_high"] = 1 - df["price"] / df["high_30d"]
    df["weekday"] = df["captured_at"].dt.day_name()

    print(f"\nTracking {df['url'].nunique()} products, {len(df)} snapshots in total.")

    print("\n=== Latest price per product (first 20) ===")
    latest = df.groupby("url").tail(1)
    print(latest[["name", "price", "high_30d", "drop_from_high"]].head(20).to_string(index=False))

    print("\n=== Average % change by weekday ===")
    print(df.groupby("weekday")["pct_change"].mean())

    print("\n=== Drops of 10% or more ===")
    big_drops = df[df["pct_change"] <= -0.10]
    if big_drops.empty:
        print("None yet.")
    else:
        print(big_drops[["name", "captured_at", "price", "pct_change"]].to_string(index=False))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "collect"
    if cmd == "collect":
        collect()
    elif cmd == "analyze":
        analyze()
    else:
        print(__doc__)
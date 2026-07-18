"""픽투셀로 내보낸 상품 URL을 기록해서, 다음 수집 때 중복을 걸러낸다."""

import os
from datetime import datetime

import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
ARCHIVE_PATH = os.path.join(DATA_DIR, "scraped_archive.csv")
COLUMNS = ["url", "title", "keyword", "exported_at"]


def load_archive() -> pd.DataFrame:
    if not os.path.exists(ARCHIVE_PATH):
        return pd.DataFrame(columns=COLUMNS)
    return pd.read_csv(ARCHIVE_PATH)


def get_archived_urls() -> set:
    df = load_archive()
    if "url" not in df.columns:
        return set()
    return set(df["url"].dropna().astype(str))


def add_to_archive(rows, keyword=None):
    """rows: [{"url": ..., "title": ...}, ...]"""
    df = load_archive()
    now = datetime.now().isoformat(timespec="seconds")
    new_rows = [
        {"url": r.get("url"), "title": r.get("title"), "keyword": keyword, "exported_at": now}
        for r in rows
        if r.get("url")
    ]
    if not new_rows:
        return df

    combined = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
    combined = combined.drop_duplicates(subset=["url"], keep="first")
    os.makedirs(DATA_DIR, exist_ok=True)
    combined.to_csv(ARCHIVE_PATH, index=False)
    return combined


def clear_archive():
    if os.path.exists(ARCHIVE_PATH):
        os.remove(ARCHIVE_PATH)

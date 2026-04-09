"""
core/downloader.py
Downloads wallpapers from Unsplash. All filtering happens here.
"""
import os
import random
import requests
from PIL import Image

from core.manager import INBOX, get_unique_path

MIN_HEIGHT = 1080


def _fetch_one_query(query, count, unsplash_key, min_width, existing_files, existing_ids):
    """
    Try to download up to `count` photos for a single query.
    Returns number of images actually saved.
    Mutates existing_files and existing_ids in place.
    """
    params = {
        "client_id":      unsplash_key,
        "query":          query,
        "count":          count,
        "sig":            random.randint(1, 1_000_000_000),
        "orientation":    "landscape",
        "content_filter": "high",
    }

    try:
        resp = requests.get(
            "https://api.unsplash.com/photos/random",
            params=params, timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        results = payload if isinstance(payload, list) else [payload]
    except requests.RequestException:
        return 0

    downloaded = 0
    for photo in results:
        width  = photo.get("width", 0)
        height = photo.get("height", 0)

        if width < min_width or height < MIN_HEIGHT:
            continue
        if height > 0 and not (1.6 < width / height < 1.9):
            continue

        img_id   = photo["id"]
        filename = f"unsplash_{img_id}.jpg"

        if img_id in existing_ids or filename in existing_files:
            continue

        file_path = get_unique_path(INBOX, filename)

        try:
            img_data = requests.get(photo["urls"]["full"], timeout=30).content
            with open(file_path, "wb") as f:
                f.write(img_data)

            with Image.open(file_path) as img:
                if img.width < min_width or img.height < MIN_HEIGHT:
                    os.remove(file_path)
                    continue

            # Required by Unsplash API terms — trigger download event
            dl_loc = photo.get("links", {}).get("download_location", "")
            if dl_loc:
                requests.get(dl_loc, params={"client_id": unsplash_key}, timeout=10)

            existing_files.add(filename)
            existing_ids.add(img_id)
            downloaded += 1

        except (requests.RequestException, OSError):
            if os.path.exists(file_path):
                os.remove(file_path)

    return downloaded


def fetch(count=5, queries=None, unsplash_key="", min_width=1920):
    """
    Download `count` wallpapers from Unsplash.
    Tries queries in shuffled order until at least 1 image is downloaded
    or all queries are exhausted (max 5 query attempts).
    Returns the number of successfully downloaded images.
    """
    if not unsplash_key or unsplash_key == "YOUR_ACCESS_KEY_HERE":
        return 0

    if not queries:
        queries = ["nature", "landscape"]

    existing_files = set(os.listdir(INBOX))
    existing_ids = {
        f[len("unsplash_"):-len(".jpg")]
        for f in existing_files
        if f.startswith("unsplash_") and f.endswith(".jpg")
    }

    shuffled = queries[:]
    random.shuffle(shuffled)
    max_attempts = min(5, len(shuffled))

    downloaded = 0
    for query in shuffled[:max_attempts]:
        downloaded += _fetch_one_query(
            query, count, unsplash_key, min_width, existing_files, existing_ids
        )
        if downloaded >= 1:
            break

    return downloaded

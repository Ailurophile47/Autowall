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

# ── Per-fetch state (reset at the start of every fetch() call) ────────────────
# Maps basename → query used, so callers can attach category to metadata.
_fetched_categories: dict = {}
# Set to True if any query attempt hit a network / HTTP error.
_had_network_error: bool = False


def get_and_clear_fetched_categories() -> dict:
    """Return {filename: category} from the last fetch() call and clear it."""
    global _fetched_categories
    result = dict(_fetched_categories)
    _fetched_categories.clear()
    return result


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
        global _had_network_error
        _had_network_error = True
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
            _fetched_categories[filename] = query
            downloaded += 1

        except (requests.RequestException, OSError):
            if os.path.exists(file_path):
                os.remove(file_path)

    return downloaded


def fetch(count=5, queries=None, unsplash_key="", min_width=1920, prefs=None, bias_ratio=0.7):
    """
    Download `count` wallpapers from Unsplash.

    Query selection uses a configurable exploitation / exploration strategy:
      - `bias_ratio` of the time: pick with preference weighting
      - the rest of the time: pick a random query

    prefs — optional dict of {query: score} from metadata["__preferences__"].
            If None or empty, all queries are treated equally (cold start).

    Returns:
      int >= 0  — number of images downloaded
      -1        — network / API error (no internet or key problem)
    """
    global _fetched_categories, _had_network_error
    _fetched_categories.clear()
    _had_network_error = False

    if not unsplash_key or unsplash_key == "YOUR_ACCESS_KEY_HERE":
        return 0

    if not queries:
        queries = ["nature", "landscape"]

    # Cold start: give every query an equal base weight
    effective_prefs = prefs if prefs else {q: 1 for q in queries}

    existing_files = set(os.listdir(INBOX))
    existing_ids = {
        f[len("unsplash_"):-len(".jpg")]
        for f in existing_files
        if f.startswith("unsplash_") and f.endswith(".jpg")
    }

    # Build an ordered list of queries using weighted + exploration
    remaining = list(queries)
    ordered = []
    max_attempts = min(5, len(remaining))
    for _ in range(max_attempts):
        if not remaining:
            break
        try:
            if random.random() < max(0.0, min(1.0, bias_ratio)):
                # Exploitation: weight by preferences (floor at 1)
                weights = [max(effective_prefs.get(q, 1), 1) for q in remaining]
                chosen = random.choices(remaining, weights=weights, k=1)[0]
            else:
                # Exploration: pick any query uniformly
                chosen = random.choice(remaining)
        except Exception:
            chosen = random.choice(remaining)
        ordered.append(chosen)
        remaining.remove(chosen)

    downloaded = 0
    for query in ordered:
        downloaded += _fetch_one_query(
            query, count, unsplash_key, min_width, existing_files, existing_ids
        )
        if downloaded >= 1:
            break

    if downloaded == 0 and _had_network_error:
        return -1   # signals offline / API unreachable

    return downloaded

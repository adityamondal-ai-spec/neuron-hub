#!/usr/bin/env python3
"""Find local business leads via Google Places API, drop them into leads/inbox/."""
import os
import re
import sys
import argparse
from datetime import date
from pathlib import Path

import requests

VAULT = Path(__file__).resolve().parent.parent
INBOX = VAULT / "leads" / "inbox"
LOG_DIR = VAULT / "logs"

TEXTSEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

DEFAULT_NICHES = ["jewellers", "cafes", "dental clinics"]
DEFAULT_LOCATION = "Your City, State, Country"
MAX_PER_NICHE = 5


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "lead"


def existing_slugs() -> set:
    slugs = set()
    for sub in ("inbox", "contacted", "warm", "won"):
        folder = VAULT / "leads" / sub
        if folder.exists():
            slugs.update(p.stem for p in folder.glob("*.md"))
    return slugs


def text_search(query: str, key: str) -> list:
    resp = requests.get(TEXTSEARCH_URL, params={"query": query, "key": key}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    status = data.get("status")
    if status not in ("OK", "ZERO_RESULTS"):
        raise RuntimeError(f"{status} - {data.get('error_message', '')}")
    return data.get("results", [])


def place_details(place_id: str, key: str) -> dict:
    fields = "name,formatted_address,formatted_phone_number,website,rating,user_ratings_total"
    resp = requests.get(
        DETAILS_URL,
        params={"place_id": place_id, "fields": fields, "key": key},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "OK":
        raise RuntimeError(data.get("status"))
    return data.get("result", {})


def write_lead(niche: str, place: dict, details: dict, seen: set):
    name = details.get("name") or place.get("name") or "Unknown"
    slug = slugify(name)
    if slug in seen:
        return None
    seen.add(slug)

    website = details.get("website", "")
    phone = details.get("formatted_phone_number", "")
    address = details.get("formatted_address", place.get("formatted_address", ""))
    rating = details.get("rating", "")
    reviews = details.get("user_ratings_total", "")

    body = f"""---
business: {name}
niche: {niche}
status: new
website: {website}
phone: {phone}
address: {address}
rating: {rating}
reviews: {reviews}
place_id: {place.get('place_id', '')}
found_date: {date.today().isoformat()}
---

# {name}

## Pitch angle
(fill during Scout/Writer pass)
"""
    path = INBOX / f"{slug}.md"
    path.write_text(body)
    return slug


def main():
    parser = argparse.ArgumentParser(description="Find local business leads via Google Places API")
    parser.add_argument("--niches", nargs="+", default=DEFAULT_NICHES)
    parser.add_argument("--location", default=DEFAULT_LOCATION)
    parser.add_argument("--max-per-niche", type=int, default=MAX_PER_NICHE)
    args = parser.parse_args()

    key = os.environ.get("GOOGLE_PLACES_KEY")
    if not key:
        print("ERROR: GOOGLE_PLACES_KEY env var not set. Export it before running.", file=sys.stderr)
        sys.exit(1)

    INBOX.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    seen = existing_slugs()
    created = []

    for niche in args.niches:
        query = f"{niche} in {args.location}"
        try:
            results = text_search(query, key)
        except Exception as e:
            print(f"[{niche}] search failed: {e}", file=sys.stderr)
            continue

        count = 0
        for place in results:
            if count >= args.max_per_niche:
                break
            try:
                details = place_details(place["place_id"], key)
            except Exception as e:
                print(f"[{niche}] details failed for {place.get('name')}: {e}", file=sys.stderr)
                continue
            slug = write_lead(niche, place, details, seen)
            if slug:
                created.append(slug)
                count += 1

    log_path = LOG_DIR / f"find_leads_{date.today().isoformat()}.log"
    with log_path.open("a") as f:
        f.write(f"{date.today().isoformat()} - created {len(created)} leads: {', '.join(created)}\n")

    print(f"Done. {len(created)} new lead(s) written to {INBOX}")
    for slug in created:
        print(f"  - {slug}")


if __name__ == "__main__":
    main()

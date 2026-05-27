"""Parse playwright page snapshot YAML to extract Facebook Marketplace listings."""
import re
from typing import Dict, List, Optional


def parse_listing_link(text: str) -> Optional[Dict]:
    """Parse a marketplace listing link text into title, price, location.

    Patterns observed:
        "Title in City, ST $123"
        "Title in City, ST $36 $45"  (discounted + original price)
        "Title in $123 Ships to you"
        "Title in City, ST Free"
        "Title, $123, City, ST, listing 1234567890"
    """
    # Location pattern: "City, ST" (city name + comma + 2-letter state)
    loc_pattern = r'([A-Z][a-zA-Z\s.]+,\s*[A-Z]{2})'

    # "Title in City, ST $price [$original]"
    match = re.match(
        r'^(.+)\s+in\s+' + loc_pattern + r'\s+(\$[\d,]+(?:\.\d{2})?)(?:\s+\$[\d,]+(?:\.\d{2})?)?$',
        text
    )
    if match:
        return {"title": match.group(1).strip(), "location": match.group(2).strip(), "price": match.group(3).strip()}

    # "Title in City, ST Free"
    match = re.match(r'^(.+)\s+in\s+' + loc_pattern + r'\s+(Free)$', text)
    if match:
        return {"title": match.group(1).strip(), "location": match.group(2).strip(), "price": "Free"}

    # "Title in $123 Ships to you"
    match = re.match(r'^(.+?)\s+in\s+(\$[\d,]+(?:\.\d{2})?)\s+Ships to you$', text)
    if match:
        return {"title": match.group(1).strip(), "location": "Ships to you", "price": match.group(2).strip()}

    # "Title $123" (no location)
    match = re.match(r'^(.+?)\s+(\$[\d,]+(?:\.\d{2})?)$', text)
    if match:
        return {"title": match.group(1).strip(), "price": match.group(2).strip()}

    # "Title, $123, City, ST, listing 1234567890"
    match = re.match(
        r'^(.+?),\s*(\$[\d,]+(?:\.\d{2})?|Free),\s*((?:[^,]+,\s*[A-Z]{2})|Ships to you),\s*listing\s+\d+$',
        text,
    )
    if match:
        return {
            "title": match.group(1).strip(),
            "price": match.group(2).strip(),
            "location": match.group(3).strip(),
        }

    return None


def extract_listings_from_snapshot(snapshot_text: str) -> List[Dict]:
    """Extract marketplace listings from a playwright page snapshot YAML.

    Finds all lines containing /marketplace/item/ links and their associated
    link text, then parses them into structured listing data.
    """
    listings = []
    seen_ids = set()
    lines = snapshot_text.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i]

        # Look for link lines with marketplace item text
        # Pattern: - link "Title in City, ST $123" [ref=...] [cursor=pointer]:
        link_match = re.match(r'^\s*- link "(.+?)"(?:\s+\[ref=.*?\])?:?$', line)
        if link_match:
            link_text = link_match.group(1)

            # Check if the next line has a marketplace item URL
            if i + 1 < len(lines):
                url_line = lines[i + 1]
                url_match = re.search(r'/marketplace/item/(\d+)/', url_line)
                if url_match:
                    item_id = url_match.group(1)
                    if item_id not in seen_ids:
                        parsed = parse_listing_link(link_text)
                        if parsed:
                            seen_ids.add(item_id)
                            listings.append({
                                "item_id": item_id,
                                "title": parsed["title"],
                                "price": parsed["price"],
                                "location": parsed.get("location"),
                                "url": f"/marketplace/item/{item_id}/",
                            })

        # Also handle link lines without text but with /url containing marketplace item
        # These have the data in child generic elements (non-logged-in view)
        if '/marketplace/item/' in line and '- /url:' in line:
            url_match = re.search(r'/marketplace/item/(\d+)/', line)
            if url_match:
                item_id = url_match.group(1)
                if item_id not in seen_ids:
                    # Look forwards for generic children with price/title/location
                    price = None
                    title = None
                    location = None
                    for j in range(i + 1, min(i + 15, len(lines))):
                        child = lines[j].strip()
                        # Stop if we hit another link or same-level element
                        if child.startswith('- link ') or child.startswith('- /url:'):
                            break
                        # Match "generic [ref=...]: $123" or "generic [ref=...]: FREE"
                        gen_match = re.match(r'^-?\s*generic \[ref=\w+\]:\s*(.+)$', child)
                        if gen_match:
                            val = gen_match.group(1).strip()
                            if val.startswith('$') or val == 'FREE' or val == 'Free':
                                price = val
                            elif re.match(r'^[A-Z].*,\s*[A-Z]{2}$', val):
                                location = val
                            elif val and not title and val != 'Just listed':
                                title = val

                    if title and price:
                        seen_ids.add(item_id)
                        listings.append({
                            "item_id": item_id,
                            "title": title,
                            "price": price,
                            "location": location,
                            "url": f"/marketplace/item/{item_id}/",
                        })

        i += 1

    return listings

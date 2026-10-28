import re

RESULTS_RE = re.compile(r"^\d+\s+results$")
PAGE_RE = re.compile(r'- button "Page (\d+)(?: is your current page)?"')
CURRENT_RE = re.compile(r'- button "Page (\d+) is your current page"')
DATE_RE = re.compile(r"^[A-Z][a-z]+ \d{1,2}, \d{4}$")
BUTTON_RE = re.compile(r'- button "((?:[^"\\]|\\.)*)"')
NUMBERED_OBJECTIVE_RE = re.compile(r"^\d+\.\s+")
ROW_STATUS_TOKENS = {"applied"}


def _text(line: str) -> str | None:
    if "- text:" not in line:
        return None
    value = line.split("- text:", 1)[1].strip()
    return value[1:-1] if value.startswith('"') and value.endswith('"') else value


def _button(line: str) -> str | None:
    match = BUTTON_RE.search(line)
    if match is None:
        return None
    value = match.group(1)
    return value.replace('\\"', '"').replace("\\\\", "\\")


def extract_total_pages(snapshot_text: str) -> int:
    pages = [int(match.group(1)) for match in PAGE_RE.finditer(snapshot_text)]
    return max(pages) if pages else 1


def extract_current_page(snapshot_text: str) -> int:
    match = CURRENT_RE.search(snapshot_text)
    return int(match.group(1)) if match else 1


def extract_opportunities_from_snapshot(snapshot_text: str, page_number: int) -> list[dict]:
    tokens = []
    collecting = False
    for line in snapshot_text.splitlines():
        text = _text(line)
        if not collecting:
            collecting = bool(text and RESULTS_RE.fullmatch(text))
            continue
        if PAGE_RE.search(line) or 'button "Next page"' in line or text == "Features":
            break
        if text and text.strip() not in {"●", "Posted"}:
            tokens.append(text.strip())

    rows = []
    index = 0
    while index < len(tokens):
        if tokens[index] in ROW_STATUS_TOKENS:
            index += 1
            continue
        title = tokens[index]
        is_new = index + 1 < len(tokens) and tokens[index + 1] == "NEW!"
        index += 2 if is_new else 1
        if index + 2 >= len(tokens):
            raise ValueError(f"Incomplete opportunity record after title: {title}")
        opportunity_type, category, posted_date = tokens[index:index + 3]
        if not DATE_RE.fullmatch(posted_date):
            raise ValueError(f"Unexpected posted date for '{title}': {posted_date}")
        rows.append(
            {
                "id": re.sub(r"[^a-z0-9]+", "-", f"{title}-{posted_date}".casefold()).strip("-"),
                "title": title,
                "opportunity_type": opportunity_type,
                "category": category,
                "posted_date": posted_date,
                "is_new": is_new,
                "page_number": page_number,
            }
        )
        index += 3
    return rows


def extract_learning_objectives_from_snapshot(snapshot_text: str) -> list[str]:
    texts = []
    for line in snapshot_text.splitlines():
        text = _text(line)
        if text is not None:
            texts.append(text.strip())

    expected_count = None
    for index in range(len(texts) - 3):
        if texts[index] == "Learning Objective" and texts[index + 1] == "(" and texts[index + 3] == ")":
            if not texts[index + 2].isdigit():
                raise ValueError(f"Learning Objective count must be numeric: {texts[index + 2]}")
            expected_count = int(texts[index + 2])
            break
    if expected_count is None:
        raise ValueError("Learning Objective section not found in detail snapshot.")

    objectives = []
    for line in snapshot_text.splitlines():
        button = _button(line)
        if button is None or not NUMBERED_OBJECTIVE_RE.match(button):
            continue
        if not button.endswith("Expanded"):
            raise ValueError(f"Learning objective button missing Expanded suffix: {button}")
        objectives.append(button.removesuffix("Expanded").strip())

    if len(objectives) != expected_count:
        raise ValueError(
            f"Expected {expected_count} learning objectives, found {len(objectives)} in detail snapshot."
        )
    return objectives

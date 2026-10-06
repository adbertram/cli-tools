"""Decode Studio's per-post moderation read: GET /mod/v1/getPenaltyDetails/?vid=<id>.

TikTok web has no Account check page; this endpoint is what Studio's post
analytics view calls to render "Visibility restricted". The enums below are
copied from Studio's own bundle (appeal status, reason code, penalty type) and
its English strings, observed 2026-10-06. Unlisted codes stay undecoded.
"""
PENALTY_PATH = "/mod/v1/getPenaltyDetails/"
APPEAL_STATUS = {0: "can_submit", 1: "cannot_submit", 2: "no_penalty", 3: "reviewing",
                 4: "succeeded", 5: "failed", 6: "timeout"}
# NR: ineligible for the For You feed and restricted in search. NFF: ineligible for the For You feed.
PENALTY_TYPES = {0: "NR", 1: "NFF"}
REASONS = {
    0: "Ineligible for the For You feed",
    1: "Ineligible for the For You feed",
    2: "Tobacco and alcohol products",
    3: "Violent and graphic content",
    4: "Dangerous stunts and sports",
    5: "Overtly sexualized content",
    6: "Spam, inauthentic, or misleading content",
    7: "Unoriginal, low-quality, and QR code content",
    8: "Minor safety",
    9: "Unoriginal, low-quality, and QR code content",
    10: "Reproduced account",
    11: "Deceptive behaviors and fake engagement",
}
UNREAD = {"eligibility": None, "reasons": [], "appeal_status": None, "penalty_type": None,
          "penalized_at": None, "penalty_issuer": None, "penalty_error": None}


def _code(value):
    """Studio sends reason codes and penalty dates as decimal strings and reads them with Number()."""
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 12:
        return int(value)
    raise ValueError("reason code")


def normalize_penalty(payload):
    """Whitelist one penalty read. Unreadable or malformed reads stay unknown."""
    if not isinstance(payload, dict) or type(payload.get("status_code")) is not int:
        return {**UNREAD, "penalty_error": "malformed penalty response"}
    if payload["status_code"] != 0:
        message = payload.get("status_msg")
        return {**UNREAD, "penalty_error": f"status_code {payload['status_code']}: {message if isinstance(message, str) else ''}".strip()}
    penalties = payload.get("penalties")
    appeal = payload.get("appeal_status")
    try:
        if penalties is not None and not isinstance(penalties, list):
            raise ValueError("penalties")
        if appeal is not None and type(appeal) is not int:
            raise ValueError("appeal_status")
        reasons, dates, issuers = [], [], []
        for penalty in penalties or []:
            for raw in penalty["reason_codes"]:
                code = _code(raw)
                # Studio only shows server-supplied titles for codes it cannot decode itself.
                supplied = next((info.get("title") for info in penalty.get("penalty_reason_info_list") or []
                                 if str(info.get("code")) == str(raw) and isinstance(info.get("title"), str)), None)
                if code not in [reason["code"] for reason in reasons]:
                    reasons.append({"code": code, "title": REASONS.get(code, supplied)})
            if penalty.get("date") is not None:
                dates.append(_code(penalty["date"]))
            if isinstance(penalty.get("issuer"), str):
                issuers.append(penalty["issuer"])
    except (KeyError, TypeError, ValueError, AttributeError):
        return {**UNREAD, "penalty_error": "malformed penalty response"}
    restricted = bool(penalties)
    penalty_type = (payload.get("top_penalty_details") or {}).get("penalty_type") if restricted else None
    return {
        "eligibility": "restricted" if restricted else "no_penalty",
        "reasons": reasons,
        "appeal_status": APPEAL_STATUS.get(appeal),
        "penalty_type": PENALTY_TYPES.get(penalty_type) if type(penalty_type) is int else None,
        "penalized_at": min(dates) if dates else None,
        "penalty_issuer": issuers[0] if issuers else None,
        "penalty_error": None,
    }

from pluralsight_author_cli.parsers import (
    extract_current_page,
    extract_learning_objectives_from_snapshot,
    extract_opportunities_from_snapshot,
    extract_total_pages,
)


PAGE_ONE_SNAPSHOT = """
- generic [ref=e1]:
  - heading "Opportunities" [level=1] [ref=e2]
  - text: 93 results
  - button "sort opportunitiesNewest to oldest" [ref=e3]
  - text: UX Accessibility: Designing for Mobile
  - text: NEW!
  - img "play circle icon" [ref=e4]
  - text: Video Course
  - text: ●
  - text: Product & UX
  - text: ●
  - text: Posted
  - text: May 11, 2026
  - img "bookmark icon" [ref=e5]
  - text: Execute Phishing Campaign with SET
  - text: NEW!
  - img "labs icon" [ref=e6]
  - text: Desktop Lab
  - text: ●
  - text: Security
  - text: ●
  - text: Posted
  - text: May 08, 2026
  - img "bookmark icon" [ref=e7]
  - text: The MITRE ATT&CK Framework
  - text: NEW!
  - img "play circle icon" [ref=e8]
  - text: Video Course
  - text: ●
  - text: Security
  - text: ●
  - text: Posted
  - text: May 08, 2026
  - img "bookmark icon" [ref=e9]
  - button "Page 1 is your current page" [ref=e10]
  - button "Page 2" [ref=e11]
  - button "Page 3" [ref=e12]
  - button "Page 4" [ref=e13]
  - button "Next page" [ref=e14]
  - text: Features
"""


PAGE_TWO_SNAPSHOT = """
- generic [ref=e1]:
  - heading "Opportunities" [level=1] [ref=e2]
  - text: 93 results
  - button "sort opportunitiesNewest to oldest" [ref=e3]
  - text: Abuse and Operational Attacks for AI
  - img "play circle icon" [ref=e4]
  - text: Video Course
  - text: ●
  - text: Security
  - text: ●
  - text: Posted
  - text: May 05, 2026
  - img "bookmark icon" [ref=e5]
  - text: Lab: Semantic Search and Recommendation System
  - img "labs icon" [ref=e6]
  - text: Code Lab
  - text: ●
  - text: Artificial Intelligence
  - text: ●
  - text: Posted
  - text: April 30, 2026
  - img "bookmark icon" [ref=e7]
  - button "Previous page" [ref=e8]
  - button "Page 1" [ref=e9]
  - button "Page 2 is your current page" [ref=e10]
  - button "Page 3" [ref=e11]
  - button "Page 4" [ref=e12]
  - button "Next page" [ref=e13]
  - text: Features
"""


PAGE_WITH_APPLIED_MARKER = """
- generic:
  - text: "86 results"
  - text: "OpenAI Codex Advanced Features"
  - text: "Video Course"
  - text: "Artificial Intelligence"
  - text: "Posted"
  - text: "April 23, 2026"
  - text: "applied"
  - text: "OpenAI Codex in Practice"
  - text: "Video Course"
  - text: "Artificial Intelligence"
  - text: "Posted"
  - text: "April 23, 2026"
  - text: "Features"
"""


DETAIL_SNAPSHOT = """
- generic:
  - text: "Product Strategy: Steering with Evidence"
  - text: "Learning Objective"
  - text: "("
  - text: "4"
  - text: ")"
  - button "Apply"
  - button "Copy link"
  - button "1. Evaluate a strategic decision against a chain of evidence. Naming what would have to be true for the decision to be right, including when data should lead versus when strategy must lead and data followsExpanded"
  - button "2. Distinguish signal from noise in product data, identifying common patterns of data-theater: vanity metrics, post-hoc rationalization, confounded experiments, and biased samplesExpanded"
  - button "3. Defend a strategic call in a roadmap review or exec conversation using a structured evidence argument that holds up against pushbackExpanded"
  - button "4. Define success metrics for non-deterministic AI features, separating technical model performance from actual strategic business outcomes. (e.g., Just because the LLM is fast doesn't mean it increased our revenue)Expanded"
"""


def test_extract_pagination_metadata():
    assert extract_total_pages(PAGE_ONE_SNAPSHOT) == 4
    assert extract_current_page(PAGE_ONE_SNAPSHOT) == 1
    assert extract_current_page(PAGE_TWO_SNAPSHOT) == 2


def test_extract_page_one_opportunities():
    results = extract_opportunities_from_snapshot(PAGE_ONE_SNAPSHOT, page_number=1)

    assert len(results) == 3
    assert results[0] == {
        "id": "ux-accessibility-designing-for-mobile-may-11-2026",
        "title": "UX Accessibility: Designing for Mobile",
        "opportunity_type": "Video Course",
        "category": "Product & UX",
        "posted_date": "May 11, 2026",
        "is_new": True,
        "page_number": 1,
    }
    assert results[1]["title"] == "Execute Phishing Campaign with SET"
    assert results[1]["id"] == "execute-phishing-campaign-with-set-may-08-2026"
    assert results[1]["opportunity_type"] == "Desktop Lab"
    assert results[2]["title"] == "The MITRE ATT&CK Framework"


def test_extract_page_two_opportunities():
    results = extract_opportunities_from_snapshot(PAGE_TWO_SNAPSHOT, page_number=2)

    assert len(results) == 2
    assert results[0]["is_new"] is False
    assert results[0]["title"] == "Abuse and Operational Attacks for AI"
    assert results[1]["category"] == "Artificial Intelligence"
    assert results[1]["posted_date"] == "April 30, 2026"


def test_extract_opportunities_skips_applied_status_marker_between_rows():
    results = extract_opportunities_from_snapshot(PAGE_WITH_APPLIED_MARKER, page_number=2)

    assert [item["id"] for item in results] == [
        "openai-codex-advanced-features-april-23-2026",
        "openai-codex-in-practice-april-23-2026",
    ]


def test_extract_learning_objectives_from_snapshot():
    assert extract_learning_objectives_from_snapshot(DETAIL_SNAPSHOT) == [
        "1. Evaluate a strategic decision against a chain of evidence. Naming what would have to be true for the decision to be right, including when data should lead versus when strategy must lead and data follows",
        "2. Distinguish signal from noise in product data, identifying common patterns of data-theater: vanity metrics, post-hoc rationalization, confounded experiments, and biased samples",
        "3. Defend a strategic call in a roadmap review or exec conversation using a structured evidence argument that holds up against pushback",
        "4. Define success metrics for non-deterministic AI features, separating technical model performance from actual strategic business outcomes. (e.g., Just because the LLM is fast doesn't mean it increased our revenue)",
    ]

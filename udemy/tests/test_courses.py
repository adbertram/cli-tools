from types import SimpleNamespace

import pytest

from udemy_cli.client import ClientError, UdemyClient
from udemy_cli.commands import courses


class RecordingSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return SimpleNamespace(
            status_code=200,
            headers={},
            json=lambda: self.payload,
            text="",
            raise_for_status=lambda: None,
        )


class RecordingBrowserSession:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def request_json(self, method, path, *, json_body=None):
        self.calls.append({"method": method, "path": path, "json_body": json_body})
        key = (method, path)
        if key not in self.responses:
            raise AssertionError(f"No response registered for {method} {path}")
        return self.responses[key]


def make_client(monkeypatch, payload):
    config = SimpleNamespace(
        personal_access_token="token-123",
        base_url="https://www.udemy.com/instructor-api/v1",
        browser_session="udemy",
        has_api_credentials=lambda: True,
        get_missing_credentials=lambda: [],
        get_browser=lambda: None,
    )
    client = UdemyClient(config=config)
    client.session = RecordingSession(payload)
    return client


def make_browser_client(responses=None):
    config = SimpleNamespace(
        personal_access_token="",
        base_url="https://www.udemy.com/instructor-api/v1",
        browser_session="udemy",
        has_api_credentials=lambda: False,
        get_missing_credentials=lambda: [],
        get_browser=lambda: None,
    )
    client = UdemyClient(config=config)
    client.browser = RecordingBrowserSession(responses)
    return client


def test_list_courses_uses_taught_courses_endpoint_with_api_level_limit(monkeypatch):
    client = make_client(
        monkeypatch,
        {
            "count": 1,
            "next": None,
            "previous": None,
            "results": [{"id": "x01RGl7O3QqgTj3CMM15wSKlg==", "title": "Course", "url": "/course/course/"}],
        },
    )

    courses = client.list_courses(limit=25)

    assert [course.id for course in courses] == ["x01RGl7O3QqgTj3CMM15wSKlg=="]
    assert client.session.calls == [
        {
            "method": "GET",
            "url": "https://www.udemy.com/instructor-api/v1/taught-courses/courses/",
            "headers": {
                "Authorization": "Bearer token-123",
                "Accept": "application/json",
            },
            "params": {"page_size": 25, "fields[course]": "@all"},
            "json": None,
            "timeout": 30,
        }
    ]


def test_get_course_returns_matching_course_from_taught_courses(monkeypatch):
    client = make_client(
        monkeypatch,
        {
            "count": 2,
            "next": None,
            "previous": None,
            "results": [
                {"id": "course-one", "title": "First", "url": "/course/first/"},
                {"id": "course-two", "title": "Second", "url": "/course/second/"},
            ],
        },
    )

    course = client.get_course("course-two")

    assert course.id == "course-two"
    assert course.title == "Second"


def test_get_course_fails_when_course_id_is_not_taught(monkeypatch):
    client = make_client(
        monkeypatch,
        {
            "count": 1,
            "next": None,
            "previous": None,
            "results": [{"id": "course-one", "title": "Course", "url": "/course/course/"}],
        },
    )

    with pytest.raises(ClientError, match="Course missing-course was not found"):
        client.get_course("missing-course")


def test_get_course_management_fetches_all_non_curriculum_manage_sections():
    responses = {
        (
            "GET",
            "/api-2.0/courses/4902274/manage-menu/",
        ): {"groups": [{"items": [{"key": "goals"}, {"key": "curriculum"}, {"key": "basics"}]}]},
        (
            "GET",
            "/api-2.0/courses/4902274/?fields[course]=requirements_data,what_you_will_learn_data,who_should_attend_data",
        ): {
            "requirements_data": {"items": ["No PowerShell experience needed."]},
            "what_you_will_learn_data": {"items": ["Install PowerShell Core"]},
            "who_should_attend_data": {"items": ["System administrators"]},
        },
        (
            "GET",
            "/api-2.0/courses/4902274/?fields[course]=title,headline,description,locale,instructional_level_id,primary_category,primary_subcategory,all_course_has_labels,image_750x422,promo_asset,intended_category,category_locked,category_applicable,label_applicable,min_summary_words,landing_preview_as_guest_url,organization_id,is_published&fields[course_label]=@min",
        ): {
            "title": "PowerShell for Sysadmins",
            "instructional_level_id": "1",
            "primary_category": {"id": 294, "title": "IT & Software"},
        },
        ("GET", "/api-2.0/course-categories/"): {"results": [{"id": 294, "title": "IT & Software"}]},
        ("GET", "/api-2.0/course-categories/294/subcategories/"): {
            "results": [{"id": 138, "title": "Operating Systems & Servers"}]
        },
        ("GET", "/api-2.0/locales/?page_size=200"): {"results": [{"locale": "en_US", "title": "English (US)"}]},
        (
            "GET",
            "/api-2.0/courses/4902274/?fields[course]=base_price_detail,is_paid,min_price,num_paid_switches,price_updated_date,_class,features,id,is_published,published_time,is_practice_test_course,num_published_practice_tests,is_owner,is_owner_opted_into_deals,owner_is_premium_instructor,url&fields[course_feature]=promotions_create",
        ): {"base_price_detail": {"amount": 24.99, "currency": "usd"}, "is_paid": True},
        ("GET", "/api-2.0/price-tiers/"): {"results": [{"amount": 24.99, "currency": "usd"}]},
        ("GET", "/api-2.0/pricing/4902274/course-price-range/get/"): {
            "min_list_price": {"amount": 9.99},
            "max_list_price": {"amount": 89.99},
        },
        (
            "GET",
            "/api-2.0/courses/4902274/coupons-v2/meta/",
        ): {"remaining_coupon_count": 3, "referral_code": "BE75F41378F63F77FE01"},
        (
            "GET",
            "/api-2.0/courses/4902274/coupons-v2/?ordering=end_time,-created&page=1&invalid=false&page_size=10",
        ): {"results": []},
        (
            "GET",
            "/api-2.0/courses/4902274/coupons-v2/?ordering=-created&page=1&search=&invalid=true&page_size=10",
        ): {"results": [{"code": "FREEPS"}]},
        ("GET", "/api-2.0/courses/4902274/course-messages/"): {
            "results": [{"message_type": "welcome", "content": "<p>Welcome</p>"}]
        },
        ("GET", "/api-2.0/users/me/courses/4902274/instructor-course-statuses/"): {
            "results": [{"id": 210600, "status": 3, "respond_time_frame": None, "available_date": None}]
        },
        ("GET", "/api-2.0/courses/4902274/settings/"): {"results": []},
        (
            "GET",
            "/api-2.0/courses/4902274/translations/?page_size=50&fields[course_translation]=@all",
        ): {"results": [{"locale": "de_DE", "availability": "public"}]},
        (
            "GET",
            "/api-2.0/courses/4902274/?fields[caption]=asset_id,locale_id,title,url,source,status,confidence_threshold,modified,is_edit,is_edit_of_autocaption&fields[asset]=asset_type,id,captions&fields[course]=can_edit,primary_subcategory,promo_asset,locale,is_published,organization_id,is_in_any_ufb_content_collection,is_language_course&fields[locale]=@default",
        ): {"locale": {"locale": "en_US"}, "promo_asset": {"id": 44737590}},
        (
            "GET",
            "/api-2.0/courses/4902274/captions/?fields[caption]=asset_id,locale_id,title,url,source,status,confidence_threshold,modified,is_edit,is_edit_of_autocaption&locale=en_US",
        ): {"results": []},
        (
            "GET",
            "/api-2.0/courses/4902274/draft-captions/?fields[draft_caption]=asset_id,locale_id,source,status,published_caption_id,modified&locale=en_US",
        ): {"results": []},
        (
            "GET",
            "/api-2.0/courses/4902274/?fields[course]=quality_status,quality_review_process&fields[quality_review_process]=last_submitted_date",
        ): {"quality_status": "approved", "quality_review_process": {"id": 671722}},
        (
            "GET",
            "/api-2.0/quality-review-processes/671722/quality-criteria-feedbacks/?fields[quality_criteria_feedback]=comment_thread,is_marked_as_fixed,quality_criteria,rating&fields[quality_criteria]=solution_url,solution_text,title",
        ): {"results": []},
        (
            "GET",
            "/api-2.0/courses/4902274/?fields[course]=has_students,can_invite",
        ): {"has_students": True, "can_invite": False},
        (
            "GET",
            "/api-2.0/courses/4902274/students/?ordering=-enrollment_date&q=&page_size=10&page=1&fields[user]=@default,completion_ratio,enrollment_date,is_organization_enrollment,last_accessed,question_count,question_answer_count",
        ): {"results": []},
    }
    client = make_browser_client(responses)

    management = client.get_course_management("4902274")

    assert set(management["sections"]) == {
        "goals",
        "basics",
        "pricing",
        "promotions",
        "communications",
        "availability",
        "accessibility",
        "captions",
        "feedback",
        "students",
    }
    assert "curriculum" not in management["sections"]
    assert management["sections"]["promotions"]["meta"]["remaining_coupon_count"] == 3
    assert management["sections"]["students"]["students"]["results"] == []


def test_update_course_management_sends_browser_updates_for_each_writable_section():
    responses = {
        ("GET", "/api-2.0/users/me/courses/4902274/instructor-course-statuses/"): {
            "results": [{"id": 210600, "status": 3, "respond_time_frame": None, "available_date": None}]
        },
        ("PATCH", "/api-2.0/courses/4902274/?category=course-goals"): {"ok": True},
        ("PATCH", "/api-2.0/courses/4902274/?category=course-basics"): {"ok": True},
        (
            "PATCH",
            "/api-2.0/courses/4902274/?fields[course]=base_price_detail,is_paid,min_price,num_paid_switches,price_updated_date",
        ): {"ok": True},
        ("POST", "/api-2.0/courses/4902274/course-messages/"): {"ok": True},
        ("PUT", "/api-2.0/users/me/courses/4902274/instructor-course-statuses/210600/"): {"ok": True},
        ("POST", "/api-2.0/courses/4902274/settings/"): {"ok": True},
        ("PATCH", "/api-2.0/courses/4902274/translations/de_DE/"): {"ok": True},
        ("POST", "/api-2.0/courses/4902274/coupons-v2/"): {"ok": True},
    }
    client = make_browser_client(responses)

    result = client.update_course_management(
        "4902274",
        {
            "goals": {
                "requirements_data": {"items": ["No PowerShell experience needed."]},
                "what_you_will_learn_data": {"items": ["Install PowerShell Core"]},
                "who_should_attend_data": {"items": ["System administrators"]},
            },
            "basics": {
                "title": "PowerShell for Sysadmins",
                "headline": "Getting Started",
                "description": "<p>Course description</p>",
                "locale": "en_US",
                "instructional_level_id": 1,
                "category_id": 294,
                "subcategory_id": 138,
                "labels_json": "{\"approved_labels\":{\"ids\":[6746],\"primary\":6746},\"proposed_labels\":{\"ids\":[],\"primary\":null}}",
                "promo_asset": 44737590,
            },
            "pricing": {"price_money": {"amount": 22.99, "currency": "usd"}},
            "communications": [{"message_type": "welcome", "content": "<p>Welcome</p>"}],
            "availability": {
                "status": 1,
                "respond_time_frame": "12 hours",
                "available_date": None,
                "apply_to_all_courses": False,
            },
            "accessibility": {"are_captions_provided": "on"},
            "captions": [{"locale": "de_DE", "availability": "restricted"}],
            "promotions": [
                {
                    "code": "CODETEST123456",
                    "discount_value": 12.99,
                    "discount_strategy": "long_discount",
                    "start_time": "2026-04-20T18:30:00.000Z",
                }
            ],
        },
    )

    assert result["updated_sections"] == [
        "goals",
        "basics",
        "pricing",
        "communications",
        "availability",
        "accessibility",
        "captions",
        "promotions",
    ]
    assert client.browser.calls == [
        {
            "method": "PATCH",
            "path": "/api-2.0/courses/4902274/?category=course-goals",
            "json_body": {
                "requirements_data": {"items": ["No PowerShell experience needed."]},
                "what_you_will_learn_data": {"items": ["Install PowerShell Core"]},
                "who_should_attend_data": {"items": ["System administrators"]},
            },
        },
        {
            "method": "PATCH",
            "path": "/api-2.0/courses/4902274/?category=course-basics",
            "json_body": {
                "title": "PowerShell for Sysadmins",
                "headline": "Getting Started",
                "description": "<p>Course description</p>",
                "locale": "en_US",
                "instructional_level_id": 1,
                "category_id": 294,
                "subcategory_id": 138,
                "labels_json": "{\"approved_labels\":{\"ids\":[6746],\"primary\":6746},\"proposed_labels\":{\"ids\":[],\"primary\":null}}",
                "promo_asset": 44737590,
            },
        },
        {
            "method": "PATCH",
            "path": "/api-2.0/courses/4902274/?fields[course]=base_price_detail,is_paid,min_price,num_paid_switches,price_updated_date",
            "json_body": {"price_money": {"amount": 22.99, "currency": "usd"}},
        },
        {
            "method": "POST",
            "path": "/api-2.0/courses/4902274/course-messages/",
            "json_body": [{"message_type": "welcome", "content": "<p>Welcome</p>"}],
        },
        {
            "method": "GET",
            "path": "/api-2.0/users/me/courses/4902274/instructor-course-statuses/",
            "json_body": None,
        },
        {
            "method": "PUT",
            "path": "/api-2.0/users/me/courses/4902274/instructor-course-statuses/210600/",
            "json_body": {"status": 1, "respond_time_frame": "12 hours", "available_date": None},
        },
        {
            "method": "POST",
            "path": "/api-2.0/courses/4902274/settings/",
            "json_body": {"setting": "are_captions_provided", "value": "on"},
        },
        {
            "method": "PATCH",
            "path": "/api-2.0/courses/4902274/translations/de_DE/",
            "json_body": {"availability": "restricted"},
        },
        {
            "method": "POST",
            "path": "/api-2.0/courses/4902274/coupons-v2/",
            "json_body": {
                "code": "CODETEST123456",
                "discount_value": 12.99,
                "discount_strategy": "long_discount",
                "start_time": "2026-04-20T18:30:00.000Z",
            },
        },
    ]


def test_update_course_management_rejects_unknown_sections_before_browser_calls():
    client = make_browser_client({})

    with pytest.raises(ClientError, match="Unsupported course management section: curriculum"):
        client.update_course_management("4902274", {"curriculum": {"title": "Do not update"}})

    assert client.browser.calls == []


def test_courses_commands_are_marked_for_api_credentials():
    assert courses.COMMAND_CREDENTIALS == {
        "list": ["personal_access_token"],
        "get": ["personal_access_token"],
        "management": ["browser_session"],
        "update": ["browser_session"],
    }

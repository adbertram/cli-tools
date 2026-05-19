"""Buttondown API models."""
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import ConfigDict, Field

from .base import CLIModel


class ButtondownModel(CLIModel):
    """Base model that preserves every field returned by Buttondown."""

    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_by_alias=True,
        validate_by_name=True,
    )


class SubscriberSource(str, Enum):
    ADMIN = "admin"
    API = "api"
    CARRD = "carrd"
    COMMENT = "comment"
    EMBEDDED_FORM = "embedded_form"
    FORM = "form"
    IMPORT = "import"
    MEMBERFUL = "memberful"
    NETLIFY = "netlify"
    ORGANIC = "organic"
    PATREON = "patreon"
    STRIPE = "stripe"
    USER = "user"
    ZAPIER = "zapier"


class SubscriberType(str, Enum):
    BLOCKED = "blocked"
    COMPLAINED = "complained"
    CHURNING = "churning"
    CHURNED = "churned"
    GIFTED = "gifted"
    UNACTIVATED = "unactivated"
    UNPAID = "unpaid"
    UNDELIVERABLE = "undeliverable"
    PREMIUM = "premium"
    PAST_DUE = "past_due"
    PAUSED = "paused"
    REGULAR = "regular"
    REMOVED = "removed"
    TRIALED = "trialed"
    UNSUBSCRIBED = "unsubscribed"
    UPCOMING = "upcoming"


class SubscriberUndeliverabilityReason(str, Enum):
    ACCESS_DENIED = "access_denied"
    AUTHENTICATION_ISSUE = "authentication_issue"
    DELIVERY_EXPIRED = "delivery_expired"
    DOMAIN_BLOCKED = "domain_blocked"
    EMAIL_BLOCKED = "email_blocked"
    HARD_BOUNCE = "hard_bounce"
    IP_BLOCKED = "ip_blocked"
    IP_UNDELIVERABLE = "ip_undeliverable"
    MALFORMED = "malformed"
    ON_ESP_DENYLIST = "on_esp_denylist"
    OTHER = "other"
    OUT_OF_STORAGE = "out_of_storage"
    PROBLEMATIC_URL = "problematic_url"
    RATE_LIMITED = "rate_limited"
    SPAM = "spam"
    TRANSIENT = "transient"
    DISABLED = "disabled"
    DOES_NOT_EXIST = "does_not_exist"
    SPF_FAILED = "spf_failed"
    UNREACHABLE = "unreachable"


class EmailStatus(str, Enum):
    DRAFT = "draft"
    MANAGED_BY_RSS = "managed_by_rss"
    ABOUT_TO_SEND = "about_to_send"
    SCHEDULED = "scheduled"
    IN_FLIGHT = "in_flight"
    PAUSED = "paused"
    DELETED = "deleted"
    ERRORED = "errored"
    SENT = "sent"
    IMPORTED = "imported"
    THROTTLED = "throttled"
    RESENDING = "resending"
    TRANSACTIONAL = "transactional"
    SUPPRESSED = "suppressed"


class EmailSource(str, Enum):
    API = "api"
    IMPORT = "import"
    APP = "app"
    EXTERNAL_FEED = "external_feed"


class EmailType(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    PREMIUM = "premium"
    FREE = "free"
    CHURNED = "churned"
    ARCHIVAL = "archival"


class ArchivalMode(str, Enum):
    DISABLED = "disabled"
    ENABLED = "enabled"
    ENABLED_FOR_PAID_SUBSCRIBERS = "enabled_for_paid_subscribers"
    ENABLED_FOR_SUBSCRIBERS = "enabled_for_subscribers"


class EmailCommentingMode(str, Enum):
    DISABLED = "disabled"
    ENABLED = "enabled"
    ENABLED_FOR_PAID_SUBSCRIBERS = "enabled_for_paid_subscribers"


class Subscriber(ButtondownModel):
    id: str = Field(frozen=True)
    creation_date: str
    email_address: str
    referral_code: str
    secondary_id: int
    source: SubscriberSource
    tags: List[str]
    type: SubscriberType
    utm_campaign: str
    utm_medium: str
    utm_source: str
    avatar_url: Optional[str] = None
    churn_date: Optional[str] = None
    commenting_disabled: Optional[bool] = None
    click_rate: Optional[float] = None
    clicked_count: Optional[int] = None
    delivered_count: Optional[int] = None
    email_transitions: Optional[List[Dict[str, Any]]] = None
    firewall_reasons: Optional[List[Dict[str, Any]]] = None
    form_id: Optional[str] = None
    gift_subscription_message: Optional[str] = None
    ip_address: Optional[str] = None
    last_click_date: Optional[str] = None
    last_open_date: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None
    open_count: Optional[int] = None
    open_rate: Optional[float] = None
    purchased_by: Optional[str] = None
    purchased_message: Optional[str] = None
    referrer_url: Optional[str] = None
    risk_score: Optional[float] = None
    stripe_coupon: Optional[Dict[str, Any]] = None
    stripe_customer: Optional[Dict[str, Any]] = None
    stripe_customer_id: Optional[str] = None
    subscriber_import_id: Optional[str] = None
    transitions: Optional[List[Dict[str, Any]]] = None
    undeliverability_date: Optional[str] = None
    undeliverability_reason: Optional[SubscriberUndeliverabilityReason] = None
    unsubscription_date: Optional[str] = None
    unsubscription_reason: Optional[str] = None
    upgrade_date: Optional[str] = None


class Email(ButtondownModel):
    id: str = Field(frozen=True)
    creation_date: str
    absolute_url: str
    body: str
    canonical_url: str
    commenting_mode: EmailCommentingMode
    description: str
    archival_mode: ArchivalMode
    featured: bool
    filters: Dict[str, Any]
    image: str
    modification_date: str
    related_email_ids: List[str]
    should_trigger_pay_per_email_billing: bool
    source: EmailSource
    status: EmailStatus
    subject: str
    analytics: Optional[Dict[str, Any]] = None
    attachments: Optional[List[str]] = None
    email_type: Optional[EmailType] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    publish_date: Optional[str] = None
    review_mode: Optional[str] = None
    secondary_id: Optional[int] = None
    slug: Optional[str] = None
    suppression_reason: Optional[str] = None
    template: Optional[str] = None


class Tag(ButtondownModel):
    name: str
    color: str
    id: str = Field(frozen=True)
    creation_date: str
    secondary_id: int
    description: Optional[str] = None
    public_description: Optional[str] = None
    subscriber_editable: bool = False


class TagAnalytics(ButtondownModel):
    created_subscribers: int
    click_rate: float
    open_rate: float


class ActionResult(ButtondownModel):
    ok: bool
    action: str
    id: Optional[str] = None


class ExternalFeedStatus(str, Enum):
    ACTIVE = "active"
    FAILING = "failing"
    INACTIVE = "inactive"
    DELETED = "deleted"


class ExternalFeedBehavior(str, Enum):
    DRAFT = "draft"
    EMAILS = "emails"


class ExternalFeedCadence(str, Enum):
    EVERY = "every"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ExternalFeed(ButtondownModel):
    id: str = Field(frozen=True)
    creation_date: str
    url: str
    status: ExternalFeedStatus
    behavior: ExternalFeedBehavior
    cadence: ExternalFeedCadence
    cadence_metadata: Dict[str, Any] = Field(default_factory=dict)
    filters: Dict[str, Any] = Field(default_factory=dict)
    subject: str
    body: str
    label: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    skip_old_items: bool = False
    last_checked_date: Optional[str] = None


class AutomationStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class Automation(ButtondownModel):
    id: str = Field(frozen=True)
    creation_date: str
    name: str
    status: AutomationStatus
    trigger: str
    actions: List[Dict[str, Any]]
    filters: Dict[str, Any]
    metadata: Dict[str, Any] = Field(default_factory=dict)
    should_evaluate_filter_after_delay: bool = False


class Render(ButtondownModel):
    content: str


class Account(ButtondownModel):
    username: str
    email_address: str


class Newsletter(ButtondownModel):
    id: str = Field(frozen=True)
    username: str
    name: str
    enabled_features: List[str] = Field(default_factory=list)
    domain: Optional[str] = None
    from_name: Optional[str] = None
    description: Optional[str] = None


def create_subscriber(data: dict) -> Subscriber:
    return Subscriber(**data)


def create_email(data: dict) -> Email:
    return Email(**data)


def create_tag(data: dict) -> Tag:
    return Tag(**data)


def create_tag_analytics(data: dict) -> TagAnalytics:
    return TagAnalytics(**data)


def create_external_feed(data: dict) -> ExternalFeed:
    return ExternalFeed(**data)


def create_automation(data: dict) -> Automation:
    return Automation(**data)


def create_render(data: dict) -> Render:
    return Render(**data)


def create_account(data: dict) -> Account:
    return Account(**data)


def create_newsletter(data: dict) -> Newsletter:
    return Newsletter(**data)

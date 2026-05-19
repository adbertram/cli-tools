"""Pydantic models for FreshBooks Customer/Client entities."""
from typing import Optional
from pydantic import BaseModel, Field


class Customer(BaseModel):
    """FreshBooks Customer/Client entity."""

    # Read-only fields (set by server)
    id: str = Field(frozen=True, description="Customer ID")
    userid: Optional[str] = Field(default=None, frozen=True, description="Associated user ID")
    accounting_systemid: Optional[str] = Field(default=None, frozen=True, description="Accounting system ID")

    # Name fields
    fname: Optional[str] = Field(default=None, description="First name")
    lname: Optional[str] = Field(default=None, description="Last name")
    organization: Optional[str] = Field(default=None, description="Organization/company name")

    # Contact info
    email: Optional[str] = Field(default=None, description="Email address")
    mob_phone: Optional[str] = Field(default=None, description="Mobile phone")
    home_phone: Optional[str] = Field(default=None, description="Home phone")
    bus_phone: Optional[str] = Field(default=None, description="Business phone")
    fax: Optional[str] = Field(default=None, description="Fax number")

    # Address - billing
    p_street: Optional[str] = Field(default=None, description="Billing street address")
    p_street2: Optional[str] = Field(default=None, description="Billing street address line 2")
    p_city: Optional[str] = Field(default=None, description="Billing city")
    p_province: Optional[str] = Field(default=None, description="Billing state/province")
    p_code: Optional[str] = Field(default=None, description="Billing postal/zip code")
    p_country: Optional[str] = Field(default=None, description="Billing country")

    # Address - shipping
    s_street: Optional[str] = Field(default=None, description="Shipping street address")
    s_street2: Optional[str] = Field(default=None, description="Shipping street address line 2")
    s_city: Optional[str] = Field(default=None, description="Shipping city")
    s_province: Optional[str] = Field(default=None, description="Shipping state/province")
    s_code: Optional[str] = Field(default=None, description="Shipping postal/zip code")
    s_country: Optional[str] = Field(default=None, description="Shipping country")

    # Settings
    currency_code: Optional[str] = Field(default="USD", description="Preferred currency code")
    language: Optional[str] = Field(default="en", description="Preferred language")
    note: Optional[str] = Field(default=None, description="Internal notes about customer")

    # Visibility
    vis_state: Optional[int] = Field(default=0, description="Visibility state (0=active, 1=deleted, 2=archived)")

    # Timestamps (read-only)
    updated: Optional[str] = Field(default=None, frozen=True, description="Last updated timestamp")

    class Config:
        """Pydantic model configuration."""
        extra = "allow"  # Allow extra fields from API response


class CustomerCreate(BaseModel):
    """Model for creating a new customer."""

    email: str = Field(description="Email address")
    fname: str = Field(description="First name")
    lname: str = Field(description="Last name")
    organization: str = Field(description="Organization/company name")
    mob_phone: Optional[str] = Field(default=None, description="Mobile phone")
    home_phone: Optional[str] = Field(default=None, description="Home phone")
    bus_phone: Optional[str] = Field(default=None, description="Business phone")
    p_street: Optional[str] = Field(default=None, description="Billing street address")
    p_city: Optional[str] = Field(default=None, description="Billing city")
    p_province: Optional[str] = Field(default=None, description="Billing state/province")
    p_code: Optional[str] = Field(default=None, description="Billing postal/zip code")
    p_country: Optional[str] = Field(default=None, description="Billing country")
    currency_code: Optional[str] = Field(default="USD", description="Preferred currency code")
    language: Optional[str] = Field(default="en", description="Preferred language")
    note: Optional[str] = Field(default=None, description="Internal notes")


class CustomerUpdate(BaseModel):
    """Model for updating an existing customer."""

    email: Optional[str] = Field(default=None, description="Email address")
    fname: Optional[str] = Field(default=None, description="First name")
    lname: Optional[str] = Field(default=None, description="Last name")
    organization: Optional[str] = Field(default=None, description="Organization/company name")
    mob_phone: Optional[str] = Field(default=None, description="Mobile phone")
    home_phone: Optional[str] = Field(default=None, description="Home phone")
    bus_phone: Optional[str] = Field(default=None, description="Business phone")
    p_street: Optional[str] = Field(default=None, description="Billing street address")
    p_city: Optional[str] = Field(default=None, description="Billing city")
    p_province: Optional[str] = Field(default=None, description="Billing state/province")
    p_code: Optional[str] = Field(default=None, description="Billing postal/zip code")
    p_country: Optional[str] = Field(default=None, description="Billing country")
    currency_code: Optional[str] = Field(default=None, description="Preferred currency code")
    language: Optional[str] = Field(default=None, description="Preferred language")
    note: Optional[str] = Field(default=None, description="Internal notes")

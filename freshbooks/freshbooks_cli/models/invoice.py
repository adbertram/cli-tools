"""Pydantic models for FreshBooks Invoice entities."""
from datetime import date
from typing import List, Optional
from pydantic import BaseModel, Field, SerializeAsAny


class Amount(BaseModel):
    """Monetary amount with currency code."""

    amount: str = Field(default="0.00", description="Amount value as string")
    code: str = Field(default="USD", description="Currency code")


class LineItem(BaseModel):
    """Invoice line item."""

    name: str = Field(default="", description="Line item name/description")
    description: str = Field(default="", description="Detailed description")
    qty: str = Field(default="1", description="Quantity")
    unit_cost: Optional[Amount] = Field(default=None, description="Unit cost")
    amount: Optional[Amount] = Field(default=None, description="Total amount for line")
    taxName1: Optional[str] = Field(default=None, description="First tax name")
    taxAmount1: Optional[str] = Field(default=None, description="First tax amount")


class Invoice(BaseModel):
    """FreshBooks Invoice entity."""

    # Read-only fields (set by server)
    id: str = Field(frozen=True, description="Invoice ID")
    invoice_number: Optional[str] = Field(default=None, frozen=True, description="Invoice number")
    accounting_systemid: Optional[str] = Field(default=None, frozen=True, description="Accounting system ID")

    # Client reference
    customerid: str = Field(description="Customer/client ID")
    organization: Optional[str] = Field(default=None, description="Client organization name")
    fname: Optional[str] = Field(default=None, description="Client first name")
    lname: Optional[str] = Field(default=None, description="Client last name")

    # Dates
    create_date: Optional[str] = Field(default=None, description="Invoice creation date (YYYY-MM-DD)")
    due_date: Optional[str] = Field(default=None, description="Invoice due date (YYYY-MM-DD)")
    due_offset_days: Optional[int] = Field(default=30, description="Days until due from creation")
    updated: Optional[str] = Field(default=None, frozen=True, description="Last updated timestamp")

    # Status
    v3_status: Optional[str] = Field(default=None, description="Invoice status (draft, sent, viewed, paid, overdue)")
    status: Optional[int] = Field(default=None, description="Legacy status code")
    payment_status: Optional[str] = Field(default=None, description="Payment status")

    # Amounts
    amount: Optional[Amount] = Field(default=None, description="Total invoice amount")
    outstanding: Optional[Amount] = Field(default=None, description="Outstanding balance")
    paid: Optional[Amount] = Field(default=None, description="Amount paid")
    discount_value: Optional[str] = Field(default=None, description="Discount value")
    discount_total: Optional[Amount] = Field(default=None, description="Total discount amount")

    # Content
    currency_code: str = Field(default="USD", description="Currency code")
    language: str = Field(default="en", description="Invoice language")
    lines: Optional[List[SerializeAsAny[LineItem]]] = Field(default=None, description="Invoice line items")
    notes: Optional[str] = Field(default=None, description="Invoice notes")
    terms: Optional[str] = Field(default=None, description="Payment terms")
    po_number: Optional[str] = Field(default=None, description="Purchase order number")

    # Visibility
    vis_state: Optional[int] = Field(default=0, description="Visibility state (0=active, 1=deleted, 2=archived)")

    class Config:
        """Pydantic model configuration."""
        extra = "allow"  # Allow extra fields from API response


class InvoiceCreate(BaseModel):
    """Model for creating a new invoice."""

    customerid: str = Field(description="Customer/client ID")
    lines: List[SerializeAsAny[LineItem]] = Field(description="Invoice line items")
    create_date: Optional[str] = Field(default=None, description="Invoice date (YYYY-MM-DD)")
    due_offset_days: int = Field(default=30, description="Days until due")
    currency_code: str = Field(default="USD", description="Currency code")
    language: str = Field(default="en", description="Invoice language")
    notes: Optional[str] = Field(default=None, description="Invoice notes")
    terms: Optional[str] = Field(default=None, description="Payment terms")
    po_number: Optional[str] = Field(default=None, description="Purchase order number")


class InvoiceUpdate(BaseModel):
    """Model for updating an existing invoice."""

    notes: Optional[str] = Field(default=None, description="Invoice notes")
    terms: Optional[str] = Field(default=None, description="Payment terms")
    po_number: Optional[str] = Field(default=None, description="Purchase order number")

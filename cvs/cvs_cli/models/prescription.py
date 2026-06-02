"""Prescription models for CVS CLI.

Based on the real CVS API response structure at:
data.getLinkedMemberPatients[].linkedIDs[].prescriptionforPatient[]
"""
from typing import Any, Dict, List, Optional

from .base import CLIModel


class RxStatus(CLIModel):
    """Prescription status details."""

    date: Optional[str] = None
    isActiveOrder: Optional[bool] = None
    parentStatus: Optional[str] = None
    statusCode: Optional[str] = None
    statusText: Optional[str] = None


class Drug(CLIModel):
    """Drug information nested inside drugInfo."""

    name: Optional[str] = None
    formName: Optional[str] = None
    strength: Optional[str] = None
    ndc: Optional[str] = None
    imageUrl: Optional[str] = None
    schedule: Optional[str] = None
    gcnSeq: Optional[str] = None
    brandName: Optional[str] = None
    genericName: Optional[str] = None
    drugType: Optional[str] = None


class DrugInfo(CLIModel):
    """Drug information wrapper."""

    drug: Optional[Drug] = None


class Prescriber(CLIModel):
    """Prescriber information."""

    firstName: Optional[str] = None
    lastName: Optional[str] = None
    phone: Optional[str] = None
    npiNumber: Optional[str] = None


class StoreDetails(CLIModel):
    """Store address and details."""

    storeNumber: Optional[str] = None
    storeName: Optional[str] = None
    address: Optional[Dict[str, Any]] = None
    phone: Optional[str] = None
    hours: Optional[Dict[str, Any]] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None


class DeliveryEligibility(CLIModel):
    """Delivery eligibility information."""

    isEligible: Optional[bool] = None
    deliveryType: Optional[str] = None
    estimatedDeliveryDate: Optional[str] = None
    deliveryOptions: Optional[List[Dict[str, Any]]] = None


class RefillEligibility(CLIModel):
    """Refill eligibility for a prescription."""

    id: Optional[str] = None
    drugName: Optional[str] = None
    isRefillable: Optional[bool] = None
    isRenewEligible: Optional[bool] = None
    numberOfRefillsRemaining: Optional[int] = None
    nextFillDate: Optional[str] = None
    expirationDate: Optional[str] = None
    lastRefillDate: Optional[str] = None
    patientFirstName: Optional[str] = None


class Prescription(CLIModel):
    """Full prescription model from the CVS API.

    All fields are Optional since many can be null in the API response.
    """

    id: Optional[str] = None
    idType: Optional[str] = None
    status: Optional[str] = None
    rxStatus: Optional[RxStatus] = None
    drugInfo: Optional[DrugInfo] = None
    prescriber: Optional[Prescriber] = None
    storeNumber: Optional[str] = None
    storeDetails: Optional[StoreDetails] = None
    quantity: Optional[int] = None
    daysSupply: Optional[int] = None
    numberOfRefillsAuthorized: Optional[int] = None
    numberOfRefillsRemaining: Optional[int] = None
    lastRefillDate: Optional[str] = None
    expirationDate: Optional[str] = None
    issueDate: Optional[str] = None
    totalPrescriptionCost: Optional[float] = None
    rxDirection: Optional[str] = None
    isRefillable: Optional[bool] = None
    isRenewEligible: Optional[bool] = None
    isTransferable: Optional[bool] = None
    deliveryEligibility: Optional[DeliveryEligibility] = None
    rxSubscriptions: Optional[List[Dict[str, Any]]] = None
    selfServeOptions: Optional[List[Dict[str, Any]]] = None
    fills: Optional[List[Dict[str, Any]]] = None
    prescriptionLookupKey: Optional[str] = None
    relevanceInfo: Optional[Dict[str, Any]] = None
    currentFillNumber: Optional[int] = None
    quantityRemaining: Optional[int] = None
    fulfilledBy: Optional[str] = None
    isFederalPlan: Optional[bool] = None
    isVaccine: Optional[bool] = None
    isHiddenByUser: Optional[bool] = None
    acceptDigitalRefill: Optional[bool] = None
    autoRenewStatus: Optional[str] = None
    nextAutoRefillDate: Optional[str] = None
    nextFillDate: Optional[str] = None
    patientFirstName: Optional[str] = None
    patientLastName: Optional[str] = None

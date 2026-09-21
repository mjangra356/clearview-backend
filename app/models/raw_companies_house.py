"""Tier 1: Raw Companies House API Schemas.
Represents the exact JSON structures returned by Companies House REST endpoints.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class CHAddress(BaseModel):
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    care_of: Optional[str] = None
    locality: Optional[str] = None
    postal_code: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    premises: Optional[str] = None

class CHAccounts(BaseModel):
    accounting_reference_date: Optional[Dict[str, Any]] = None
    last_accounts: Optional[Dict[str, Any]] = None
    next_due: Optional[str] = None
    next_made_up_to: Optional[str] = None
    overdue: Optional[bool] = False

class CHConfirmationStatement(BaseModel):
    last_made_up_to: Optional[str] = None
    next_due: Optional[str] = None
    next_made_up_to: Optional[str] = None
    overdue: Optional[bool] = False

class CHCompanyProfile(BaseModel):
    company_name: str
    company_number: str
    company_status: str
    company_status_detail: Optional[str] = None
    date_of_creation: str
    date_of_cessation: Optional[str] = None
    type: str
    jurisdiction: Optional[str] = None
    has_insolvency_history: Optional[bool] = False
    has_charges: Optional[bool] = False
    registered_office_address: Optional[CHAddress] = None
    sic_codes: Optional[List[str]] = Field(default_factory=list)
    accounts: Optional[CHAccounts] = None
    confirmation_statement: Optional[CHConfirmationStatement] = None
    links: Optional[Dict[str, str]] = None

class CHDateOfBirth(BaseModel):
    month: Optional[int] = None
    year: Optional[int] = None
    day: Optional[int] = None

class CHOfficerLinks(BaseModel):
    officer: Optional[Dict[str, str]] = None

class CHOfficer(BaseModel):
    name: str
    officer_role: str
    appointed_on: Optional[str] = None
    resigned_on: Optional[str] = None
    nationality: Optional[str] = None
    occupation: Optional[str] = None
    country_of_residence: Optional[str] = None
    date_of_birth: Optional[CHDateOfBirth] = None
    address: Optional[CHAddress] = None
    links: Optional[CHOfficerLinks] = None

class CHOfficersResponse(BaseModel):
    items: List[CHOfficer] = Field(default_factory=list)
    total_results: Optional[int] = 0
    active_count: Optional[int] = 0
    resigned_count: Optional[int] = 0

class CHAppointedTo(BaseModel):
    company_name: str
    company_number: str
    company_status: Optional[str] = "unknown"

class CHAppointmentItem(BaseModel):
    appointed_to: CHAppointedTo
    appointed_on: Optional[str] = None
    resigned_on: Optional[str] = None
    officer_role: Optional[str] = "director"

class CHAppointmentsResponse(BaseModel):
    items: List[CHAppointmentItem] = Field(default_factory=list)
    total_results: Optional[int] = 0

class CHPSCIdentification(BaseModel):
    country_registered: Optional[str] = None
    legal_form: Optional[str] = None
    legal_authority: Optional[str] = None
    place_registered: Optional[str] = None
    registration_number: Optional[str] = None

class CHPSC(BaseModel):
    name: str
    kind: str # 'individual-person-with-significant-control' | 'corporate-entity-person-with-significant-control' | 'legal-person-person-with-significant-control'
    natures_of_control: List[str] = Field(default_factory=list)
    notified_on: Optional[str] = None
    ceased_on: Optional[str] = None
    nationality: Optional[str] = None
    country_of_residence: Optional[str] = None
    date_of_birth: Optional[CHDateOfBirth] = None
    address: Optional[CHAddress] = None
    identification: Optional[CHPSCIdentification] = None

class CHPSCsResponse(BaseModel):
    items: List[CHPSC] = Field(default_factory=list)
    total_results: Optional[int] = 0
    links: Optional[Dict[str, str]] = None

class CHSearchItem(BaseModel):
    company_number: str
    title: str
    company_status: Optional[str] = None
    company_type: Optional[str] = None
    date_of_creation: Optional[str] = None
    address_snippet: Optional[str] = None
    description_snippet: Optional[str] = None

class CHSearchResponse(BaseModel):
    items: List[CHSearchItem] = Field(default_factory=list)
    total_results: Optional[int] = 0

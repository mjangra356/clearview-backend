"""Tier 2: Domain Entities.
Normalized and enriched business objects used by the compliance rule engine.
"""

from typing import List, Optional, Dict
from pydantic import BaseModel, Field

class AddressEntity(BaseModel):
    line1: str = ""
    line2: Optional[str] = None
    city: str = ""
    postal_code: str = ""
    country: str = ""
    formatted: str = ""

class AppointmentEntity(BaseModel):
    company_number: str
    company_name: str
    status: str # 'Active', 'Dissolved', 'Liquidation', etc.
    appointed_on: str
    resigned_on: Optional[str] = None
    role: str = "Director"
    is_dissolved: bool = False

class DirectorEntity(BaseModel):
    id: str
    name: str
    nationality: str = "British"
    approx_dob: Optional[str] = None
    appointed_on: str = ""
    resigned_on: Optional[str] = None
    is_active: bool = True
    roles: List[str] = Field(default_factory=lambda: ["Director"])
    address: AddressEntity
    
    # Computed metrics from appointment history
    total_appointments: int = 0
    active_appointments: int = 0
    dissolved_appointments: int = 0
    appointment_velocity_per_year: float = 0.0
    has_fatf_nationality: bool = False
    appointments: List[AppointmentEntity] = Field(default_factory=list)
    
    # Calculated risk indicators
    risk_score: int = 0
    risk_band: str = "LOW"
    risk_flags: List[dict] = Field(default_factory=list)

class PSCEntity(BaseModel):
    id: str
    name: str
    kind: str
    is_corporate: bool = False
    is_natural_person: bool = True
    is_offshore: bool = False
    nationality: str = ""
    country: str = ""
    address: AddressEntity
    
    # Corporate registration details if corporate entity
    registration_number: Optional[str] = None
    country_registered: Optional[str] = None
    legal_form: Optional[str] = None
    
    # Ownership parsed from natures_of_control
    ownership_pct_estimate: int = 0
    ownership_range_label: str = "" # e.g. "25-50%", "50-75%", "75-100%"
    has_voting_rights: bool = False
    has_appointment_rights: bool = False
    
    risk_score: int = 0
    risk_band: str = "LOW"
    
    # Recursive upstream parent PSC chain (if corporate parent owns this entity)
    upstream_pscs: List['PSCEntity'] = Field(default_factory=list)

PSCEntity.model_rebuild()

class CompanyDossier(BaseModel):
    company_number: str
    company_name: str
    status: str # 'Active', 'Dissolved', etc.
    incorporated_on: str
    age_in_months: float = 0.0
    age_in_years: float = 0.0
    is_exempt_plc: bool = False
    psc_exemption_reason: Optional[str] = None
    address: AddressEntity
    sic_code: str = ""
    sic_description: str = ""
    is_high_risk_sic: bool = False
    high_risk_sic_label: Optional[str] = None
    
    # Filing compliance
    accounts_overdue: bool = False
    confirmation_statement_overdue: bool = False
    has_insolvency_history: bool = False
    
    # Officers & PSCs
    directors: List[DirectorEntity] = Field(default_factory=list)
    pscs: List[PSCEntity] = Field(default_factory=list)
    
    # Network metrics
    shared_directorship_network: Dict[str, int] = Field(default_factory=dict)

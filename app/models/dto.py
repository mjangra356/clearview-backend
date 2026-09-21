"""Tier 3: Frontend UI DTO Projections.
Direct drop-in contracts for the ClearView dashboard user interface.
"""

from typing import List, Optional
from pydantic import BaseModel, Field

class StatusBadgeDTO(BaseModel):
    text: str
    variant: str # 'success' | 'destructive' | 'warning' | 'outline'

class CompanyHeaderDTO(BaseModel):
    company_number: str
    company_name: str
    status_badge: StatusBadgeDTO
    incorporated_date_formatted: str
    registered_address_formatted: str
    sic_formatted: str
    overall_risk_score: int # 0 - 100
    risk_band: str # 'HIGH' | 'MEDIUM' | 'LOW'
    high_flags_count: int
    medium_flags_count: int
    refreshed_at: str

class RiskDimensionDTO(BaseModel):
    key: str # 'direct' | 'directors' | 'nested' | 'ubo' | 'sector' | 'network'
    label: str # "Direct Company Risk"
    short_label: str # "Company"
    score: int # 0 - 100
    band: str # 'HIGH' | 'MEDIUM' | 'LOW'
    headline: str
    evidence: List[str] = Field(default_factory=list)
    check_ids: List[str] = Field(default_factory=list)

class DirectorAppointmentHistoryDTO(BaseModel):
    company_number: str
    company_name: str
    status: str
    role: str
    appointed_on: str
    resigned_on: Optional[str] = None
    risk_band: str

class DirectorCardDTO(BaseModel):
    id: str
    initials: str
    name: str
    roles: List[str] = Field(default_factory=list)
    nationality: str
    dob_formatted: str
    service_address_formatted: str
    active_companies_count: int
    dissolved_companies_count: int
    risk_score: int
    risk_band: str
    risk_flags: List[dict] = Field(default_factory=list)
    appointments: List[DirectorAppointmentHistoryDTO] = Field(default_factory=list)

class PSCCardDTO(BaseModel):
    id: str
    name: str
    is_corporate: bool
    ownership_pct: int
    ownership_label: str
    nationality_or_country: str
    is_offshore: bool
    risk_score: int
    risk_band: str

class OwnershipTreeNodeDTO(BaseModel):
    id: str
    name: str
    type: str # 'target' | 'offshore' | 'person' | 'company'
    company_number: Optional[str] = None
    ownership_pct: Optional[int] = None
    risk_band: str = "LOW"
    status: Optional[str] = None
    sic_description: Optional[str] = None
    is_target: bool = False
    children: List["OwnershipTreeNodeDTO"] = Field(default_factory=list)

OwnershipTreeNodeDTO.model_rebuild()

class RelatedPartyDTO(BaseModel):
    name: str
    type: str # 'Company' | 'Person'
    relationship: str
    ownership_pct: Optional[int] = None
    shared_directors: List[str] = Field(default_factory=list)
    risk_band: str

class RiskFlagDTO(BaseModel):
    id: str
    severity: str # 'HIGH' | 'MEDIUM' | 'LOW'
    category: str # 'DISSOLVED_COMPANY' | 'OFFSHORE_ENTITY' | 'RAPID_DIRECTORSHIP' | 'HIGH_RISK_SIC' | 'MISMATCH' | 'CIRCULAR_OWNERSHIP'
    title: str
    detail: str
    company_ref: Optional[str] = None

class StatutoryCheckDTO(BaseModel):
    id: str
    category: str # "Company Status", "Beneficial Ownership", etc.
    label: str # "PSC register populated (CA2006 s.790)"
    status: str # 'PASS' | 'WARN' | 'FAIL' | 'INFO'
    finding: str
    data_source: str

class UBOBreakdownItemDTO(BaseModel):
    name: str
    pct: int

class VitalMetricsDTO(BaseModel):
    directors_count: int
    pscs_count: int
    pscs_display: Optional[str] = None
    subsidiaries_count: int
    risk_flags_count: int

class FraudComplianceResponseDTO(BaseModel):
    header: CompanyHeaderDTO
    summary_narrative: str
    vital_metrics: VitalMetricsDTO
    dimensions: List[RiskDimensionDTO]
    directors: List[DirectorCardDTO]
    pscs: List[PSCCardDTO]
    psc_exemption_reason: Optional[str] = None
    ownership_tree: OwnershipTreeNodeDTO
    related_parties: List[RelatedPartyDTO]
    risk_flags: List[RiskFlagDTO]
    ubo_breakdown: List[UBOBreakdownItemDTO]
    ubo_alert: Optional[str] = None
    statutory_checks: List[StatutoryCheckDTO]

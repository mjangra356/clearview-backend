"""FastAPI Routes for Fraud & Compliance Intelligence.
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
import logging

from app.services.ch_client import ch_client
from app.services.aggregator import build_company_dossier
from app.services.rules_engine import (
    evaluate_statutory_checks,
    evaluate_risk_dimensions,
    extract_risk_flags,
)
from app.services.ownership_builder import (
    build_ownership_tree,
    build_related_parties,
    build_ubo_breakdown,
)
from app.services.llm_service import generate_investigation_summary
from app.models.dto import (
    FraudComplianceResponseDTO,
    CompanyHeaderDTO,
    StatusBadgeDTO,
    VitalMetricsDTO,
    DirectorCardDTO,
    PSCCardDTO,
    DirectorAppointmentHistoryDTO,
)
from app.models.raw_companies_house import CHSearchResponse

logger = logging.getLogger("routes")
router = APIRouter(prefix="/api")

@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "ClearView Fraud & Compliance Intelligence API",
        "timestamp": datetime.now().isoformat(),
    }

@router.get("/companies/search", response_model=CHSearchResponse)
async def search_companies(
    q: str = Query(..., min_length=1, description="Company name or registration number")
):
    """Real-time company search autocomplete against Companies House."""
    try:
        results = await ch_client.search_companies(query=q, items_per_page=10)
        return results
    except Exception as e:
        logger.error(f"Error searching companies: {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

@router.get("/companies/{company_number}/compliance", response_model=FraudComplianceResponseDTO)
async def get_company_compliance(company_number: str):
    """Real-time Fraud & Compliance evaluation for a UK company.
    Ingests live profile, officers, appointments, and PSCs from Companies House,
    runs the 16 statutory checks and 6-dimension scoring, generates an LLM summary,
    and returns the complete UI DTO payload.
    """
    clean_num = company_number.strip().zfill(8) if company_number.strip().isdigit() else company_number.strip().upper()
    
    # 1. Fetch & Normalize live data into domain dossier
    dossier = await build_company_dossier(clean_num)
    if not dossier:
        raise HTTPException(status_code=404, detail=f"Company '{clean_num}' not found on Companies House register.")
        
    # 2. Run Rules Engine: 16 Statutory Checks
    checks = evaluate_statutory_checks(dossier)
    
    # 3. Compute 6 Dimension Scores and Overall Risk Score
    dimensions, overall_score, overall_band = evaluate_risk_dimensions(checks, dossier)
    
    # 4. Extract High-Level Risk Flags
    risk_flags = extract_risk_flags(dossier, checks)
    
    # 5. Build Ownership Map, Related Parties, and UBO breakdowns
    ownership_tree = build_ownership_tree(dossier)
    related_parties = build_related_parties(dossier)
    ubo_items, ubo_alert = build_ubo_breakdown(dossier)
    
    # 6. Generate Executive Investigation Summary with LLM (or fallback)
    summary_narrative = await generate_investigation_summary(dossier, risk_flags, overall_band)
    
    # 7. Map Directors to UI DTOs
    director_cards = []
    for d in dossier.directors:
        # Generate initials
        name_parts = d.name.replace(",", " ").split()
        initials = "".join(p[0].upper() for p in name_parts[:2]) if name_parts else "DIR"
        
        # Appointments
        appts_dto = [
            DirectorAppointmentHistoryDTO(
                company_number=a.company_number,
                company_name=a.company_name,
                status=a.status,
                role=a.role,
                appointed_on=a.appointed_on,
                resigned_on=a.resigned_on,
                risk_band="HIGH" if a.is_dissolved else "MEDIUM",
            )
            for a in d.appointments[:10]
        ]
        
        director_cards.append(DirectorCardDTO(
            id=d.id,
            initials=initials,
            name=d.name,
            roles=d.roles,
            nationality=d.nationality,
            dob_formatted=d.approx_dob or "Undisclosed",
            service_address_formatted=d.address.formatted,
            active_companies_count=d.active_appointments,
            dissolved_companies_count=d.dissolved_appointments,
            risk_score=d.risk_score,
            risk_band=d.risk_band,
            risk_flags=d.risk_flags,
            appointments=appts_dto,
        ))
        
    # 8. Map PSCs to UI DTOs
    psc_cards = [
        PSCCardDTO(
            id=p.id,
            name=p.name,
            is_corporate=p.is_corporate,
            ownership_pct=p.ownership_pct_estimate,
            ownership_label=f"{p.ownership_pct_estimate}% PSC" if p.ownership_pct_estimate else "PSC",
            nationality_or_country=p.country or p.nationality or "United Kingdom",
            is_offshore=p.is_offshore,
            risk_score=p.risk_score,
            risk_band=p.risk_band,
        )
        for p in dossier.pscs
    ]
    
    # 9. Build Header DTO
    high_count = len([f for f in risk_flags if f.severity == "HIGH"])
    med_count = len([f for f in risk_flags if f.severity == "MEDIUM"])
    
    is_active = dossier.status.lower() == "active"
    status_badge = StatusBadgeDTO(
        text=dossier.status,
        variant="success" if is_active else "destructive",
    )
    
    header = CompanyHeaderDTO(
        company_number=dossier.company_number,
        company_name=dossier.company_name,
        status_badge=status_badge,
        incorporated_date_formatted=dossier.incorporated_on,
        registered_address_formatted=dossier.address.formatted,
        sic_formatted=f"SIC {dossier.sic_code} — {dossier.sic_description}" if dossier.sic_code else "No SIC registered",
        overall_risk_score=overall_score,
        risk_band=overall_band,
        high_flags_count=high_count,
        medium_flags_count=med_count,
        refreshed_at=datetime.now().strftime("%H:%M:%S"),
    )
    
    pscs_display = (
        "Exempt (LSE)"
        if (dossier.is_exempt_plc and len(dossier.pscs) == 0)
        else str(len(dossier.pscs))
    )

    vital_metrics = VitalMetricsDTO(
        directors_count=len(dossier.directors),
        pscs_count=len(dossier.pscs),
        pscs_display=pscs_display,
        subsidiaries_count=len([rp for rp in related_parties if "Connected" in rp.relationship]),
        risk_flags_count=len(risk_flags),
    )
    
    return FraudComplianceResponseDTO(
        header=header,
        summary_narrative=summary_narrative,
        vital_metrics=vital_metrics,
        dimensions=dimensions,
        directors=director_cards,
        pscs=psc_cards,
        psc_exemption_reason=dossier.psc_exemption_reason,
        ownership_tree=ownership_tree,
        related_parties=related_parties,
        risk_flags=risk_flags,
        ubo_breakdown=ubo_items,
        ubo_alert=ubo_alert,
        statutory_checks=checks,
    )

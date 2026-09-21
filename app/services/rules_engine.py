"""Fraud & Compliance Rules & Scoring Engine.

Implements the 16 statutory checks and 6-dimension risk scoring algorithm
reverse-engineered from the ClearView compliance system.
"""

import re
from typing import List, Dict, Tuple
from app.core.reference_data import FORMATION_AGENT_KEYWORDS
from app.models.domain import CompanyDossier
from app.models.dto import (
    StatutoryCheckDTO,
    RiskDimensionDTO,
    RiskFlagDTO,
)

# Status penalty points
PENALTIES: Dict[str, int] = {
    "FAIL": 40,
    "WARN": 18,
    "INFO": 0,
    "PASS": 0,
}

# Dimension to Check IDs mapping
DIMENSION_CHECKS: Dict[str, List[str]] = {
    "direct": ["ch_status", "ch_age", "ch_filings", "ch_address"],
    "directors": ["ch_dissolutions", "ch_velocity", "ch_nationality"],
    "nested": ["ch_offshore", "ch_circular", "ch_related_status"],
    "ubo": ["ch_psc_register", "ch_natural_ubo", "ch_psc_corporate", "ch_psc_threshold"],
    "sector": ["ch_sic"],
    "network": ["ch_shared_directors"],
}

DIMENSION_METADATA: Dict[str, Tuple[str, str]] = {
    "direct": ("Direct Company Risk", "Company"),
    "directors": ("Director & Key Person Risk", "Directors"),
    "nested": ("Nested Ownership Risk", "Ownership Chain"),
    "ubo": ("Beneficial Ownership Transparency", "UBO"),
    "sector": ("Sector / Regulatory Risk", "Sector"),
    "network": ("Related-Party & Network Risk", "Network"),
}

def evaluate_statutory_checks(dossier: CompanyDossier) -> List[StatutoryCheckDTO]:
    checks: List[StatutoryCheckDTO] = []
    
    # 1. Company Status
    is_active = dossier.status.lower() == "active"
    checks.append(StatutoryCheckDTO(
        id="ch_status",
        category="Company Status",
        label="Company status (Companies House register)",
        status="PASS" if is_active else "FAIL",
        finding="Active — no dissolution, strike-off, liquidation or administration recorded"
            if is_active else f"Status: {dossier.status} — entity is not actively trading per CH register",
        data_source="CH: company.status",
    ))
    
    # 2. Company Age
    m = dossier.age_in_months
    if m < 6:
        age_status = "FAIL"
        age_finding = f"Incorporated {int(m)} months ago — newly formed entity, heightened onboarding risk"
    elif m < 18:
        age_status = "WARN"
        age_finding = f"Incorporated {int(m)} months ago — less than 18 months trading history available"
    else:
        age_status = "PASS"
        age_finding = f"Incorporated {int(dossier.age_in_years)} years ago ({dossier.incorporated_on}) — sufficient trading history"
        
    checks.append(StatutoryCheckDTO(
        id="ch_age",
        category="Company Age",
        label="Company age (incorporation date)",
        status=age_status,
        finding=age_finding,
        data_source="CH: company.date_of_creation",
    ))
    
    # 3. Filing Compliance
    is_filing_default = dossier.accounts_overdue or dossier.confirmation_statement_overdue
    if is_filing_default or not is_active:
        filing_status = "FAIL"
        filing_finding = f"Company is {dossier.status} or filings overdue — confirmation statement/accounts in default"
    elif m < 24:
        filing_status = "WARN"
        filing_finding = "Company is under 24 months old — limited filing history to assess compliance"
    else:
        filing_status = "PASS"
        filing_finding = "Company has sufficient filing history. Confirmation statement & accounts up-to-date"
        
    checks.append(StatutoryCheckDTO(
        id="ch_filings",
        category="Filing Compliance",
        label="Confirmation statement & accounts filing",
        status=filing_status,
        finding=filing_finding,
        data_source="CH: confirmation_statement.overdue / accounts.overdue",
    ))
    
    # 4. PSC Register Populated
    if dossier.is_exempt_plc:
        psc_status = "INFO"
        psc_finding = "Listed PLC — PSC register exempt under CA2006 s.790B"
    elif len(dossier.pscs) > 0:
        psc_status = "PASS"
        psc_finding = f"{len(dossier.pscs)} PSC(s) registered on CH — register appears complete"
    else:
        psc_status = "FAIL"
        psc_finding = "PSC register is empty and company is not exempt — potential non-compliance with CA2006 s.790C"
        
    checks.append(StatutoryCheckDTO(
        id="ch_psc_register",
        category="PSC Register",
        label="PSC register populated (CA2006 s.790)",
        status=psc_status,
        finding=psc_finding,
        data_source="CH: persons_with_significant_control",
    ))
    
    # 5. Natural Person UBO Identifiable
    natural_pscs = [p for p in dossier.pscs if p.is_natural_person]
    offshore_pscs = [p for p in dossier.pscs if p.is_offshore]
    
    if dossier.is_exempt_plc:
        ubo_status = "INFO"
        ubo_finding = "Listed PLC — UBO identification follows Listing Rules disclosure regime, not PSC register"
    elif offshore_pscs:
        ubo_status = "FAIL"
        ubo_finding = f"PSC is an entity registered in an offshore jurisdiction ({offshore_pscs[0].country or 'Offshore'}) — natural person UBO cannot be confirmed from CH data alone"
    elif natural_pscs:
        ubo_status = "PASS"
        ubo_finding = f"{', '.join(p.name for p in natural_pscs)} identified as natural person PSC(s) on CH register"
    else:
        ubo_status = "WARN"
        ubo_finding = "No natural person PSC confirmed — only corporate PSCs registered"
        
    checks.append(StatutoryCheckDTO(
        id="ch_natural_ubo",
        category="Beneficial Ownership",
        label="Natural person UBO identifiable",
        status=ubo_status,
        finding=ubo_finding,
        data_source="CH: persons_with_significant_control[].kind / .address.country",
    ))
    
    # 6. PSC is Natural Person (Not Purely Corporate)
    if not dossier.pscs:
        corp_status = "INFO"
        corp_finding = "No PSCs registered"
    elif all(p.is_corporate for p in dossier.pscs):
        corp_status = "WARN"
        corp_finding = "All registered PSCs are corporate entities — no natural person confirmed as controlling party on CH register"
    else:
        corp_status = "PASS"
        corp_finding = f"Natural person(s) confirmed as PSC: {', '.join(p.name for p in natural_pscs)}"
        
    checks.append(StatutoryCheckDTO(
        id="ch_psc_corporate",
        category="PSC Register",
        label="PSC is natural person (not purely corporate)",
        status=corp_status,
        finding=corp_finding,
        data_source="CH: persons_with_significant_control[].kind",
    ))
    
    # 7. PSC Ownership Threshold (MLR 2017)
    high_control_pscs = [p for p in dossier.pscs if p.ownership_pct_estimate >= 75]
    standard_pscs = [p for p in dossier.pscs if p.ownership_pct_estimate >= 25]
    
    if not dossier.pscs:
        thresh_status = "INFO"
        thresh_finding = "No PSCs registered — listed company or PSC register not applicable"
    elif high_control_pscs:
        thresh_status = "WARN"
        thresh_finding = f"{high_control_pscs[0].name} holds {high_control_pscs[0].ownership_range_label} — effective control (≥75%). Verify right to appoint/remove directors."
    elif standard_pscs:
        thresh_status = "PASS"
        thresh_finding = f"PSC(s) above 25% threshold: {', '.join(f'{p.name} ({p.ownership_range_label})' for p in standard_pscs)}"
    else:
        thresh_status = "WARN"
        thresh_finding = "No PSC identified with clear 25%+ control."
        
    checks.append(StatutoryCheckDTO(
        id="ch_psc_threshold",
        category="Beneficial Ownership",
        label="PSC ownership threshold (MLR 2017 — 25%+)",
        status=thresh_status,
        finding=thresh_finding,
        data_source="CH: persons_with_significant_control[].natures_of_control",
    ))
    
    # 8. Offshore Entity in Ownership Chain
    if offshore_pscs:
        off_status = "FAIL"
        off_finding = f"Offshore PSC identified: {', '.join(p.name for p in offshore_pscs)} — beneficial ownership opacity risk"
    else:
        off_status = "PASS"
        off_finding = "No offshore entities identified in PSC register"
        
    checks.append(StatutoryCheckDTO(
        id="ch_offshore",
        category="Beneficial Ownership",
        label="Offshore entity in ownership chain",
        status=off_status,
        finding=off_finding,
        data_source="CH: persons_with_significant_control[].address.country",
    ))
    
    # 9. Circular Ownership / Cross-shareholding
    # In live evaluation, check if any director appears in both corporate PSC and target
    has_circular = False
    for p in offshore_pscs:
        if any(d.name.lower() in p.name.lower() for d in dossier.directors):
            has_circular = True
            break
            
    checks.append(StatutoryCheckDTO(
        id="ch_circular",
        category="Ownership Structure",
        label="Circular ownership / cross-shareholding",
        status="FAIL" if has_circular else "PASS",
        finding="Circular ownership pattern identified in CH officer/PSC cross-reference — potential layering structure"
            if has_circular else "No circular ownership pattern detected across disclosed CH officer and PSC data",
        data_source="CH: officers + persons_with_significant_control (cross-company analysis)",
    ))
    
    # 10. Status of Entities in Ownership Chain
    # Check if any appointment across directors points to dissolved holding companies
    has_dissolved_chain = any(d.dissolved_appointments > 0 for d in dossier.directors)
    checks.append(StatutoryCheckDTO(
        id="ch_related_status",
        category="Ownership Structure",
        label="Status of entities in ownership chain",
        status="WARN" if has_dissolved_chain else "PASS",
        finding="Dissolved or non-active entity detected in director appointment network"
            if has_dissolved_chain else "All entities in disclosed ownership chain show Active status on CH register",
        data_source="CH: company.status (applied to connected entities)",
    ))
    
    # 11. Director/PSC Dissolved Company History (Phoenix Alert)
    max_dissolved = max([d.dissolved_appointments for d in dossier.directors], default=0)
    top_dissolved_dir = next((d for d in dossier.directors if d.dissolved_appointments == max_dissolved), None)
    
    if max_dissolved >= 3:
        diss_status = "FAIL"
        diss_finding = f"{top_dissolved_dir.name if top_dissolved_dir else 'Director'} linked to {max_dissolved} dissolved/struck-off entities — phoenix company indicator"
    elif max_dissolved >= 1:
        diss_status = "WARN"
        diss_finding = f"{top_dissolved_dir.name if top_dissolved_dir else 'Director'} linked to {max_dissolved} dissolved entity — monitor for pattern"
    else:
        diss_status = "PASS"
        diss_finding = "No directors or PSCs linked to dissolved, struck-off, or liquidated companies"
        
    checks.append(StatutoryCheckDTO(
        id="ch_dissolutions",
        category="Director History",
        label="Director/PSC dissolved company history",
        status=diss_status,
        finding=diss_finding,
        data_source="CH: officers[].appointments[].company_status (cross-company)",
    ))
    
    # 12. Directorship Appointment Velocity
    max_velocity = max([d.appointment_velocity_per_year for d in dossier.directors], default=0.0)
    top_vel_dir = next((d for d in dossier.directors if d.appointment_velocity_per_year == max_velocity), None)
    
    if max_velocity >= 3.0:
        vel_status = "FAIL"
        vel_finding = f"{top_vel_dir.name if top_vel_dir else 'Director'} holds {top_vel_dir.total_appointments if top_vel_dir else ''} directorships — {max_velocity:.1f} per year. Exceeds normal commercial activity threshold."
    elif max_velocity >= 1.5:
        vel_status = "WARN"
        vel_finding = f"{top_vel_dir.name if top_vel_dir else 'Director'} holds {top_vel_dir.total_appointments if top_vel_dir else ''} directorships — rate of {max_velocity:.1f} per year. Elevated but not conclusive."
    else:
        vel_status = "PASS"
        vel_finding = "Director appointment rates within normal commercial range"
        
    checks.append(StatutoryCheckDTO(
        id="ch_velocity",
        category="Director Network",
        label="Directorship appointment velocity",
        status=vel_status,
        finding=vel_finding,
        data_source="CH: officers[].appointments (cross-company count & dates)",
    ))
    
    # 13. FATF High-Risk Nationality
    fatf_officers = [d for d in dossier.directors if d.has_fatf_nationality]
    if fatf_officers:
        nat_status = "WARN"
        nat_finding = f"{', '.join(f'{d.name} ({d.nationality})' for d in fatf_officers)} — nationality listed in FATF high-risk jurisdictions"
    else:
        nat_status = "PASS"
        nat_finding = "No directors or PSCs with FATF high-risk jurisdiction nationality identified on CH register"
        
    checks.append(StatutoryCheckDTO(
        id="ch_nationality",
        category="Director History",
        label="Director/PSC — FATF high-risk nationality",
        status=nat_status,
        finding=nat_finding,
        data_source="CH: officers[].nationality / persons_with_significant_control[].nationality",
    ))
    
    # 14. SIC / Sector Risk
    if dossier.is_high_risk_sic:
        sic_status = "WARN"
        sic_finding = f"SIC {dossier.sic_code} ({dossier.sic_description}) — categorised as high-risk under JMLSG guidance: {dossier.high_risk_sic_label}"
    else:
        sic_status = "PASS"
        sic_finding = f"SIC {dossier.sic_code or 'None'} ({dossier.sic_description}) — not on JMLSG/FATF elevated-risk sector list"
        
    checks.append(StatutoryCheckDTO(
        id="ch_sic",
        category="SIC / Sector",
        label="SIC code — JMLSG/FATF high-risk sector",
        status=sic_status,
        finding=sic_finding,
        data_source="CH: company.sic_codes[0]",
    ))
    
    # 15. Registered Address Formation Agent Indicator
    addr_line = dossier.address.line1.lower()
    has_form_agent = any(k in addr_line for k in FORMATION_AGENT_KEYWORDS)
    if has_form_agent:
        addr_status = "WARN"
        addr_finding = f'Registered address contains indicator of formation agent / virtual office use: "{dossier.address.line1}, {dossier.address.city}"'
    else:
        addr_status = "PASS"
        addr_finding = f"Registered address appears to be a physical trading address: {dossier.address.formatted}"
        
    checks.append(StatutoryCheckDTO(
        id="ch_address",
        category="Address",
        label="Registered address — formation agent indicator",
        status=addr_status,
        finding=addr_finding,
        data_source="CH: company.registered_office_address",
    ))
    
    # 16. Shared Directors Across Group Entities
    high_active_officers = [d for d in dossier.directors if d.active_appointments >= 3]
    if high_active_officers:
        net_status = "WARN"
        net_finding = f"{', '.join(f'{d.name} ({d.active_appointments} active roles)' for d in high_active_officers)} — director appears across multiple connected entities"
    else:
        net_status = "PASS"
        net_finding = "No unusual director overlap detected across group companies"
        
    checks.append(StatutoryCheckDTO(
        id="ch_shared_directors",
        category="Director Network",
        label="Shared directors across group entities",
        status=net_status,
        finding=net_finding,
        data_source="CH: officers (cross-referenced across group entities)",
    ))
    
    return checks

def evaluate_risk_dimensions(checks: List[StatutoryCheckDTO], dossier: CompanyDossier) -> Tuple[List[RiskDimensionDTO], int, str]:
    """Calculate the 6 dimension scores and composite overall score."""
    check_map = {c.id: c for c in checks}
    dimensions: List[RiskDimensionDTO] = []
    
    total_score_sum = 0
    max_dissolved = max([d.dissolved_appointments for d in dossier.directors], default=0)
    
    for key, check_ids in DIMENSION_CHECKS.items():
        dim_checks = [check_map[cid] for cid in check_ids if cid in check_map]
        
        # Base penalty sum
        base_score = sum(PENALTIES.get(c.status, 0) for c in dim_checks)
        
        # Dimension Boosters
        if key == "directors" and max_dissolved >= 3:
            base_score += 20
        elif key == "nested" and any(p.is_offshore for p in dossier.pscs):
            base_score += 20
            
        dim_score = min(100, max(0, round(base_score)))
        band = "HIGH" if dim_score >= 60 else "MEDIUM" if dim_score >= 30 else "LOW"
        
        # Determine headline & evidence
        fail_checks = [c for c in dim_checks if c.status == "FAIL"]
        warn_checks = [c for c in dim_checks if c.status == "WARN"]
        
        evidence = [c.finding for c in fail_checks + warn_checks]
        if not evidence:
            evidence = ["No adverse Companies House indicators for this dimension."]
            headline = "No material risk indicators from Companies House data."
        else:
            headline = fail_checks[0].finding if fail_checks else warn_checks[0].finding
            
        label, short_label = DIMENSION_METADATA[key]
        
        dimensions.append(RiskDimensionDTO(
            key=key,
            label=label,
            short_label=short_label,
            score=dim_score,
            band=band,
            headline=headline,
            evidence=evidence,
            check_ids=check_ids,
        ))
        total_score_sum += dim_score

    # Overall Risk Score is weighted average of dimensions + flag booster
    dim_avg = total_score_sum / len(DIMENSION_CHECKS)
    
    # Bonus for critical flags
    flag_booster = 0
    if any(p.is_offshore for p in dossier.pscs):
        flag_booster += 15
    if max_dissolved >= 3:
        flag_booster += 15
    if dossier.status.lower() != "active":
        flag_booster += 25
        
    overall_score = min(100, round(dim_avg * 0.8 + flag_booster))
    overall_band = "HIGH" if overall_score >= 60 else "MEDIUM" if overall_score >= 30 else "LOW"
    
    return dimensions, overall_score, overall_band

def extract_risk_flags(dossier: CompanyDossier, checks: List[StatutoryCheckDTO]) -> List[RiskFlagDTO]:
    """Generate the high-level risk flag badges for the right sidebar."""
    flags: List[RiskFlagDTO] = []
    
    # Offshore Entity
    offshore = [p for p in dossier.pscs if p.is_offshore]
    if offshore:
        flags.append(RiskFlagDTO(
            id="rf_offshore",
            severity="HIGH",
            category="OFFSHORE_ENTITY",
            title="Ultimate beneficial owner obscured via offshore chain",
            detail=f"Ownership held by {offshore[0].name} ({offshore[0].country or 'Offshore'}). Raises opacity concerns under MLR 2017.",
            company_ref=offshore[0].id,
        ))
        
    # Multiple Dissolutions / Phoenix
    for d in dossier.directors:
        if d.dissolved_appointments >= 3:
            flags.append(RiskFlagDTO(
                id=f"rf_diss_{d.id}",
                severity="HIGH",
                category="DISSOLVED_COMPANY",
                title="PSC/Director with 3+ dissolved entities",
                detail=f"{d.name} has been director of {d.dissolved_appointments} dissolved companies — phoenix company indicator.",
                company_ref=d.id,
            ))
            break
            
    # High-Risk SIC
    if dossier.is_high_risk_sic:
        flags.append(RiskFlagDTO(
            id="rf_sic",
            severity="MEDIUM",
            category="HIGH_RISK_SIC",
            title=f"SIC {dossier.sic_code} — Elevated risk sector",
            detail=f"Target operates in sector ({dossier.sic_description}) subject to enhanced AML scrutiny under JMLSG guidance.",
        ))
        
    # Directorship Velocity
    for d in dossier.directors:
        if d.appointment_velocity_per_year >= 3.0:
            flags.append(RiskFlagDTO(
                id=f"rf_vel_{d.id}",
                severity="MEDIUM",
                category="RAPID_DIRECTORSHIP",
                title=f"High directorship velocity — {d.name}",
                detail=f"{d.total_appointments} directorships at a velocity of {d.appointment_velocity_per_year:.1f}/year.",
                company_ref=d.id,
            ))
            break
            
    # Formation Agent / Address Mismatch
    has_form_agent = any(k in dossier.address.line1.lower() for k in FORMATION_AGENT_KEYWORDS)
    if has_form_agent:
        flags.append(RiskFlagDTO(
            id="rf_addr",
            severity="MEDIUM",
            category="MISMATCH",
            title="Shared/virtual office address detected",
            detail=f"Registered office address ({dossier.address.line1}) matches formation agent or serviced office patterns.",
        ))
        
    # Inactive Company Status
    if dossier.status.lower() != "active":
        flags.append(RiskFlagDTO(
            id="rf_status",
            severity="HIGH",
            category="INACTIVE_STATUS",
            title=f"Company status is {dossier.status}",
            detail=f"Company is not in active trading status on Companies House register.",
        ))
        
    return flags

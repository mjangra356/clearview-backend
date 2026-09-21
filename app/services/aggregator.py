"""Aggregates raw Companies House endpoints into a normalized CompanyDossier domain model.
"""

import asyncio
import re
from datetime import datetime
from typing import Optional, List, Dict
import logging

from app.core.reference_data import (
    OFFSHORE_JURISDICTIONS,
    HIGH_RISK_SICS,
    FATF_HIGH_RISK_NATIONALITIES,
)
from app.models.raw_companies_house import (
    CHCompanyProfile,
    CHOfficer,
    CHPSC,
    CHAppointmentItem,
)
from app.models.domain import (
    CompanyDossier,
    DirectorEntity,
    PSCEntity,
    AppointmentEntity,
    AddressEntity,
)
from app.services.ch_client import ch_client

logger = logging.getLogger("aggregator")

def format_address(raw_addr) -> AddressEntity:
    if not raw_addr:
        return AddressEntity()
    
    parts = []
    line1 = raw_addr.address_line_1 or raw_addr.premises or ""
    line2 = raw_addr.address_line_2 or ""
    city = raw_addr.locality or ""
    postal_code = raw_addr.postal_code or ""
    country = raw_addr.country or "United Kingdom"
    
    for p in [line1, line2, city, postal_code, country]:
        if p:
            parts.append(p)
            
    return AddressEntity(
        line1=line1,
        line2=line2 if line2 else None,
        city=city,
        postal_code=postal_code,
        country=country,
        formatted=", ".join(parts) if parts else "Address undisclosed",
    )

def parse_iso_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.split("T")[0])
    except Exception:
        return None

def compute_age_in_months(date_str: Optional[str]) -> tuple[float, float]:
    dt = parse_iso_date(date_str)
    if not dt:
        return 0.0, 0.0
    now = datetime.now()
    days = (now - dt).days
    months = days / 30.4375
    years = days / 365.25
    return months, years

async def trace_corporate_psc_chain(
    crn: str, depth: int = 1, max_depth: int = 4, visited: Optional[set] = None
) -> List[PSCEntity]:
    """Recursively traverses corporate PSC registration numbers to locate natural UBOs or offshore parents."""
    if visited is None:
        visited = set()
    
    clean_crn = crn.strip().zfill(8) if crn.strip().isdigit() else crn.strip().upper()
    if clean_crn in visited or depth > max_depth:
        return []
    visited.add(clean_crn)
    
    pscs_resp = await ch_client.get_pscs(clean_crn)
    parent_entities: List[PSCEntity] = []
    
    for idx, psc in enumerate(pscs_resp.items):
        if psc.ceased_on:
            continue
            
        is_corp = "corporate" in psc.kind.lower() or "legal" in psc.kind.lower()
        is_natural = not is_corp
        
        country = ""
        reg_num = None
        legal_form = None
        if psc.identification:
            country = psc.identification.country_registered or ""
            reg_num = psc.identification.registration_number
            legal_form = psc.identification.legal_form
        elif psc.address and psc.address.country:
            country = psc.address.country
            
        is_offshore = any(j.lower() in country.lower() for j in OFFSHORE_JURISDICTIONS)
        
        est_pct = 25
        range_label = "25%+"
        for noc in psc.natures_of_control:
            if "75-to-100" in noc:
                est_pct = 75
                range_label = "75-100%"
                break
            elif "50-to-75" in noc:
                est_pct = 60
                range_label = "50-75%"
                break
            elif "25-to-50" in noc:
                est_pct = 35
                range_label = "25-50%"
                break
                
        has_voting = any("voting-rights" in noc for noc in psc.natures_of_control)
        has_appoint = any("appoint" in noc for noc in psc.natures_of_control)
        
        psc_score = 15
        if is_offshore:
            psc_score = 90
        elif is_corp:
            psc_score = 45
        psc_band = "HIGH" if psc_score >= 60 else "MEDIUM" if psc_score >= 30 else "LOW"
        
        upstream: List[PSCEntity] = []
        if is_corp and reg_num and depth < max_depth:
            clean_reg = reg_num.strip().replace(" ", "").upper()
            upstream = await trace_corporate_psc_chain(clean_reg, depth + 1, max_depth, visited)
            
        parent_entities.append(PSCEntity(
            id=f"chain_{clean_crn}_{idx+1}",
            name=psc.name,
            kind=psc.kind,
            is_corporate=is_corp,
            is_natural_person=is_natural,
            is_offshore=is_offshore,
            nationality=psc.nationality or country or "Unknown",
            country=country,
            address=format_address(psc.address),
            registration_number=reg_num,
            country_registered=country,
            legal_form=legal_form,
            ownership_pct_estimate=est_pct,
            ownership_range_label=range_label,
            has_voting_rights=has_voting,
            has_appointment_rights=has_appoint,
            risk_score=psc_score,
            risk_band=psc_band,
            upstream_pscs=upstream,
        ))
        
    return parent_entities

async def build_company_dossier(company_number: str) -> Optional[CompanyDossier]:
    """Fetch raw CH data across profile, officers, appointments, and PSCs concurrently,
    and assemble into a typed, normalized CompanyDossier.
    """
    clean_number = company_number.strip().zfill(8) if company_number.strip().isdigit() else company_number.strip().upper()
    
    # 1. Concurrently fetch company profile, officers list, and PSCs
    profile_task = ch_client.get_company(clean_number)
    officers_task = ch_client.get_officers(clean_number)
    pscs_task = ch_client.get_pscs(clean_number)
    
    profile, officers_resp, pscs_resp = await asyncio.gather(
        profile_task, officers_task, pscs_task
    )
    
    if not profile:
        return None

    # Calculate age
    months, years = compute_age_in_months(profile.date_of_creation)
    
    # SIC Code analysis
    sic_code = profile.sic_codes[0] if profile.sic_codes else ""
    is_high_risk_sic = sic_code in HIGH_RISK_SICS
    sic_desc = HIGH_RISK_SICS.get(sic_code, "Commercial activity" if sic_code else "None registered")

    # 2. Process active directors and gather their cross-company appointments
    active_officers: List[CHOfficer] = [
        o for o in officers_resp.items
        if not o.resigned_on and "director" in o.officer_role.lower()
    ]
    
    # Extract appointment links
    appointment_tasks = []
    for officer in active_officers:
        appt_link = officer.links.officer.get("appointments") if officer.links and officer.links.officer else None
        if appt_link:
            appointment_tasks.append(ch_client.get_officer_appointments(appt_link))
        else:
            # Fallback if no link
            appointment_tasks.append(asyncio.sleep(0, result=None))
            
    appointments_results = await asyncio.gather(*appointment_tasks)
    
    directors: List[DirectorEntity] = []
    now = datetime.now()
    
    for i, officer in enumerate(active_officers):
        appts_resp = appointments_results[i]
        appts_items: List[CHAppointmentItem] = appts_resp.items if appts_resp else []
        
        # Parse appointments
        appt_entities: List[AppointmentEntity] = []
        dissolved_count = 0
        active_count = 0
        earliest_date = parse_iso_date(officer.appointed_on) or now
        
        for appt in appts_items:
            comp_status = (appt.appointed_to.company_status or "active").capitalize()
            is_dissolved = comp_status.lower() in ("dissolved", "liquidation", "administration", "struck off", "converted-closed")
            if is_dissolved:
                dissolved_count += 1
            else:
                active_count += 1
                
            appt_date = parse_iso_date(appt.appointed_on)
            if appt_date and appt_date < earliest_date:
                earliest_date = appt_date
                
            appt_entities.append(AppointmentEntity(
                company_number=appt.appointed_to.company_number,
                company_name=appt.appointed_to.company_name,
                status=comp_status,
                appointed_on=appt.appointed_on or "",
                resigned_on=appt.resigned_on,
                role=appt.officer_role,
                is_dissolved=is_dissolved,
            ))
            
        total_appts = len(appt_entities)
        years_active = max((now - earliest_date).days / 365.25, 0.5)
        velocity = total_appts / years_active if total_appts > 0 else 0.0
        
        nationality = officer.nationality or "British"
        has_fatf = any(fatf.lower() in nationality.lower() for fatf in FATF_HIGH_RISK_NATIONALITIES)
        
        # Calculate director risk score
        dir_score = 15
        dir_flags = []
        if dissolved_count >= 3:
            dir_score += 45
            dir_flags.append({
                "severity": "HIGH",
                "category": "DISSOLVED_COMPANY",
                "title": f"Director of {dissolved_count} dissolved companies",
                "detail": f"{officer.name} has been linked to {dissolved_count} dissolved/liquidated companies.",
            })
        elif dissolved_count >= 1:
            dir_score += 20
            dir_flags.append({
                "severity": "MEDIUM",
                "category": "DISSOLVED_COMPANY",
                "title": f"Director of {dissolved_count} dissolved company",
                "detail": f"{officer.name} has been linked to {dissolved_count} dissolved company.",
            })
            
        if velocity >= 3.0:
            dir_score += 25
            dir_flags.append({
                "severity": "HIGH",
                "category": "RAPID_DIRECTORSHIP",
                "title": "Rapid directorship accumulation",
                "detail": f"Directorship velocity of {velocity:.1f} companies/year exceeds normal commercial velocity.",
            })
        elif velocity >= 1.5:
            dir_score += 15
            dir_flags.append({
                "severity": "MEDIUM",
                "category": "RAPID_DIRECTORSHIP",
                "title": "Elevated directorship velocity",
                "detail": f"Directorship velocity of {velocity:.1f} companies/year.",
            })
            
        if has_fatf:
            dir_score += 25
            dir_flags.append({
                "severity": "MEDIUM",
                "category": "FATF_NATIONALITY",
                "title": "FATF High-Risk Jurisdiction Nationality",
                "detail": f"Officer holds nationality ({nationality}) under enhanced scrutiny.",
            })
            
        dir_score = min(100, dir_score)
        dir_band = "HIGH" if dir_score >= 60 else "MEDIUM" if dir_score >= 30 else "LOW"
        
        # Approx DOB
        dob_str = None
        if officer.date_of_birth and officer.date_of_birth.year:
            m = f"{officer.date_of_birth.month:02d}" if officer.date_of_birth.month else "01"
            dob_str = f"{officer.date_of_birth.year}-{m}"
            
        directors.append(DirectorEntity(
            id=f"dir_{i+1}",
            name=officer.name,
            nationality=nationality,
            approx_dob=dob_str,
            appointed_on=officer.appointed_on or "",
            resigned_on=officer.resigned_on,
            is_active=True,
            roles=["Director"],
            address=format_address(officer.address),
            total_appointments=total_appts,
            active_appointments=active_count,
            dissolved_appointments=dissolved_count,
            appointment_velocity_per_year=round(velocity, 2),
            has_fatf_nationality=has_fatf,
            appointments=appt_entities,
            risk_score=dir_score,
            risk_band=dir_band,
            risk_flags=dir_flags,
        ))

    # 3. Process Persons with Significant Control (PSCs)
    pscs: List[PSCEntity] = []
    for i, psc in enumerate(pscs_resp.items):
        if psc.ceased_on:
            continue # Skip ceased PSCs
            
        is_corp = "corporate" in psc.kind.lower() or "legal" in psc.kind.lower()
        is_natural = not is_corp
        
        # Detect offshore jurisdiction & corporate identification
        country = ""
        reg_num = None
        legal_form = None
        if psc.identification:
            country = psc.identification.country_registered or ""
            reg_num = psc.identification.registration_number
            legal_form = psc.identification.legal_form
        elif psc.address and psc.address.country:
            country = psc.address.country
            
        is_offshore = any(j.lower() in country.lower() for j in OFFSHORE_JURISDICTIONS)
        
        # Estimate ownership
        est_pct = 25
        range_label = "25%+"
        for noc in psc.natures_of_control:
            if "75-to-100" in noc:
                est_pct = 75
                range_label = "75-100%"
                break
            elif "50-to-75" in noc:
                est_pct = 60
                range_label = "50-75%"
                break
            elif "25-to-50" in noc:
                est_pct = 35
                range_label = "25-50%"
                break
                
        has_voting = any("voting-rights" in noc for noc in psc.natures_of_control)
        has_appoint = any("appoint" in noc for noc in psc.natures_of_control)
        
        psc_score = 15
        if is_offshore:
            psc_score = 90
        elif is_corp:
            psc_score = 45
            
        psc_band = "HIGH" if psc_score >= 60 else "MEDIUM" if psc_score >= 30 else "LOW"
        
        # Track recursive upstream PSC chain if corporate
        upstream_chain: List[PSCEntity] = []
        if is_corp and reg_num:
            clean_reg = reg_num.strip().replace(" ", "").upper()
            upstream_chain = await trace_corporate_psc_chain(
                clean_reg, depth=1, max_depth=4, visited={clean_number}
            )
        
        pscs.append(PSCEntity(
            id=f"psc_{i+1}",
            name=psc.name,
            kind=psc.kind,
            is_corporate=is_corp,
            is_natural_person=is_natural,
            is_offshore=is_offshore,
            nationality=psc.nationality or country or "Unknown",
            country=country,
            address=format_address(psc.address),
            registration_number=reg_num,
            country_registered=country,
            legal_form=legal_form,
            ownership_pct_estimate=est_pct,
            ownership_range_label=range_label,
            has_voting_rights=has_voting,
            has_appointment_rights=has_appoint,
            risk_score=psc_score,
            risk_band=psc_band,
            upstream_pscs=upstream_chain,
        ))

    # 4. Check statutory PSC exemptions (e.g. trading on UK regulated market / DTR5)
    exemptions_resp = None
    has_exemption_link = (profile.links and profile.links.get("exemptions")) or (pscs_resp.links and pscs_resp.links.get("exemptions"))
    if has_exemption_link:
        exemptions_resp = await ch_client.get_exemptions(clean_number)
        
    is_exempt_plc = False
    exemption_reason = None
    if exemptions_resp and isinstance(exemptions_resp, dict):
        ex_dict = exemptions_resp.get("exemptions", {})
        if "psc_exempt_as_trading_on_uk_regulated_market" in ex_dict:
            is_exempt_plc = True
            items = ex_dict["psc_exempt_as_trading_on_uk_regulated_market"].get("items", [{}])
            from_date = items[0].get("exempt_from", "2018-04-01") if items else "2018-04-01"
            exemption_reason = f"From {from_date} the company is exempt from the requirement to obtain information of its PSC because it has voting shares admitted to trading on a UK regulated market (London Stock Exchange)."
        elif "disclosure_transparency_rules_chapter_five_applies" in ex_dict:
            is_exempt_plc = True
            exemption_reason = "The company is exempt from PSC register disclosures under Chapter 5 of the Disclosure Guidance and Transparency Rules (DTR5)."
            
    if not is_exempt_plc and profile.type.lower() in ("plc", "public-limited-company") and len(pscs) == 0:
        is_exempt_plc = True
        exemption_reason = "Public Limited Company (PLC) traded on public equity markets; widely held shareholding with no single person holding ≥ 25%."
    
    return CompanyDossier(
        company_number=profile.company_number,
        company_name=profile.company_name,
        status=profile.company_status.capitalize(),
        incorporated_on=profile.date_of_creation,
        age_in_months=round(months, 1),
        age_in_years=round(years, 1),
        is_exempt_plc=is_exempt_plc,
        psc_exemption_reason=exemption_reason,
        address=format_address(profile.registered_office_address),
        sic_code=sic_code,
        sic_description=sic_desc,
        is_high_risk_sic=is_high_risk_sic,
        high_risk_sic_label=HIGH_RISK_SICS.get(sic_code),
        accounts_overdue=bool(profile.accounts and profile.accounts.overdue),
        confirmation_statement_overdue=bool(profile.confirmation_statement and profile.confirmation_statement.overdue),
        has_insolvency_history=bool(profile.has_insolvency_history),
        directors=directors,
        pscs=pscs,
    )

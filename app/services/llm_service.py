"""LLM Executive Investigation Summary Service.

Uses Gemini (or OpenAI) to synthesize live corporate findings and risk flags
into an AML/KYC executive investigation narrative.
Includes a deterministic fallback template if the LLM key is unconfigured.
"""

import os
import logging
from typing import List, Optional
from app.core.config import settings
from app.models.domain import CompanyDossier
from app.models.dto import RiskFlagDTO

logger = logging.getLogger("llm_service")

SYSTEM_PROMPT = """You are a Senior Corporate Intelligence Analyst at a major UK Tier-1 bank (NatWest ClearView).
Your task is to write a concise, authoritative, professional Executive Investigation Summary (1-2 paragraphs, max 160 words) for an AML/KYC onboarding dossier based on real-time Companies House data.
Strictly highlight:
1. Overall risk profile (HIGH, MEDIUM, or LOW).
2. Beneficial ownership transparency (PSCs, offshore entities, UBO identification).
3. Director track record (dissolved companies, appointment velocity, sector history).
4. Statutory compliance or operational anomalies (virtual office, overdue filings).
Use precise AML / MLR 2017 / POCA 2002 terminology. Do not hallucinate facts not present in the prompt.
"""

def generate_algorithmic_summary(dossier: CompanyDossier, risk_flags: List[RiskFlagDTO], overall_band: str) -> str:
    """Deterministic fallback summary generator when LLM is unavailable."""
    parts = []
    
    # Opening sentence
    parts.append(
        f"{dossier.company_name} (CRN: {dossier.company_number}) presents a {overall_band} risk profile under automated Companies House onboarding checks."
    )
    
    # Ownership & UBO
    offshore = [p for p in dossier.pscs if p.is_offshore]
    if offshore:
        parts.append(
            f"The entity's ownership chain involves an offshore entity ({offshore[0].name} in {offshore[0].country or 'an overseas secrecy jurisdiction'}), which introduces beneficial ownership opacity and mandates Enhanced Due Diligence (EDD) under MLR 2017."
        )
    elif dossier.pscs:
        natural_pscs = [p for p in dossier.pscs if p.is_natural_person]
        if natural_pscs:
            parts.append(
                f"Controlling interest is registered to {len(dossier.pscs)} PSC(s), including natural person {natural_pscs[0].name} ({natural_pscs[0].ownership_range_label})."
            )
        else:
            parts.append("All registered PSCs are corporate bodies, requiring further layer verification.")
    elif dossier.is_exempt_plc:
        parts.append("The company operates as a listed PLC exempt from standard PSC registration under CA2006 s.790B.")
    else:
        parts.append("No active PSCs are registered, representing a potential compliance gap under Companies Act 2006.")
        
    # Director track record
    dissolved_dirs = [d for d in dossier.directors if d.dissolved_appointments > 0]
    if dissolved_dirs:
        top_d = max(dissolved_dirs, key=lambda d: d.dissolved_appointments)
        if top_d.dissolved_appointments >= 3:
            parts.append(
                f"Adverse director history was detected: {top_d.name} has served on {top_d.dissolved_appointments} dissolved or liquidated companies, an indicator of potential phoenix company activity."
            )
        else:
            parts.append(
                f"Director {top_d.name} has links to {top_d.dissolved_appointments} previously dissolved company."
            )
            
    # Sector & Address
    if dossier.is_high_risk_sic:
        parts.append(
            f"The registered trade activity (SIC {dossier.sic_code}: {dossier.sic_description}) is classified as elevated risk under UK JMLSG anti-money laundering guidance."
        )
        
    return " ".join(parts)

async def generate_investigation_summary(
    dossier: CompanyDossier,
    risk_flags: List[RiskFlagDTO],
    overall_band: str,
) -> str:
    """Generate executive investigation summary using LLM with deterministic fallback."""
    gemini_key = settings.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY")
    openai_key = settings.OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY")
    
    # If no LLM key provided, return algorithmic summary
    if not gemini_key and not openai_key:
        return generate_algorithmic_summary(dossier, risk_flags, overall_band)
        
    prompt_payload = f"""Company Name: {dossier.company_name}
Registration Number: {dossier.company_number}
Status: {dossier.status}
Incorporated: {dossier.incorporated_on} (Age: {dossier.age_in_years:.1f} years)
Registered Address: {dossier.address.formatted}
SIC Code: {dossier.sic_code} ({dossier.sic_description})
Overall Assessed Risk Band: {overall_band}

PSCs ({len(dossier.pscs)}):
{chr(10).join(f"- {p.name} ({p.ownership_range_label}, Offshore: {p.is_offshore}, Country: {p.country})" for p in dossier.pscs)}

Active Directors ({len(dossier.directors)}):
{chr(10).join(f"- {d.name}: {d.total_appointments} total directorships, {d.dissolved_appointments} dissolved, velocity: {d.appointment_velocity_per_year:.1f}/yr" for d in dossier.directors)}

Detected Risk Flags:
{chr(10).join(f"- [{f.severity}] {f.title}: {f.detail}" for f in risk_flags) if risk_flags else "None"}
"""

    # Try Gemini if key available
    if gemini_key:
        try:
            from google import genai
            client = genai.Client(api_key=gemini_key)
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt_payload,
                config={'system_instruction': SYSTEM_PROMPT}
            )
            if response and response.text:
                return response.text.strip()
        except Exception as e:
            logger.warning(f"Gemini generation error: {e}. Falling back...")

    # Try OpenAI if key available
    if openai_key:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {openai_key}"},
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": prompt_payload}
                        ],
                        "max_tokens": 250,
                    }
                )
                if res.status_code == 200:
                    data = res.json()
                    return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.warning(f"OpenAI generation error: {e}. Falling back...")

    return generate_algorithmic_summary(dossier, risk_flags, overall_band)

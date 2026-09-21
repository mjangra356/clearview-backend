"""Unit tests for the Fraud & Compliance Rules Engine and Dimension Scoring.
"""

import pytest
from app.models.domain import (
    CompanyDossier,
    DirectorEntity,
    PSCEntity,
    AddressEntity,
    AppointmentEntity,
)
from app.services.rules_engine import (
    evaluate_statutory_checks,
    evaluate_risk_dimensions,
    extract_risk_flags,
)

def make_sample_dossier(
    status="Active",
    months=36.0,
    offshore=False,
    dissolved_count=0,
    velocity=1.0,
    sic="64999",
    address_line1="10 Downing Street",
) -> CompanyDossier:
    pscs = []
    if offshore:
        pscs.append(PSCEntity(
            id="psc_1",
            name="Cerulean Holdings Ltd (BVI)",
            kind="corporate-entity-person-with-significant-control",
            is_corporate=True,
            is_natural_person=False,
            is_offshore=True,
            country="British Virgin Islands",
            address=AddressEntity(line1="Road Town", country="British Virgin Islands"),
            ownership_pct_estimate=65,
            ownership_range_label="50-75%",
            risk_score=90,
            risk_band="HIGH",
        ))
    else:
        pscs.append(PSCEntity(
            id="psc_1",
            name="John Doe",
            kind="individual-person-with-significant-control",
            is_corporate=False,
            is_natural_person=True,
            is_offshore=False,
            country="United Kingdom",
            address=AddressEntity(line1="1 High St", country="United Kingdom"),
            ownership_pct_estimate=50,
            ownership_range_label="50-75%",
            risk_score=15,
            risk_band="LOW",
        ))

    appointments = []
    for i in range(dissolved_count):
        appointments.append(AppointmentEntity(
            company_number=f"1000000{i}",
            company_name=f"Old Shell {i} Ltd",
            status="Dissolved",
            appointed_on="2020-01-01",
            resigned_on="2022-01-01",
            is_dissolved=True,
        ))

    director = DirectorEntity(
        id="dir_1",
        name="Viktor Harlow" if dissolved_count >= 3 else "Jane Smith",
        nationality="British",
        address=AddressEntity(line1="14 Kensington Gate", city="London"),
        total_appointments=dissolved_count + 2,
        active_appointments=2,
        dissolved_appointments=dissolved_count,
        appointment_velocity_per_year=velocity,
        appointments=appointments,
    )

    return CompanyDossier(
        company_number="12847563",
        company_name="Test Entity Ltd",
        status=status,
        incorporated_on="2021-01-01",
        age_in_months=months,
        age_in_years=months / 12.0,
        address=AddressEntity(line1=address_line1, city="London", formatted=f"{address_line1}, London"),
        sic_code=sic,
        sic_description="Financial service activities, not elsewhere classified",
        is_high_risk_sic=(sic == "64999"),
        high_risk_sic_label="Financial services NEC (unregulated)",
        directors=[director],
        pscs=pscs,
    )

def test_statutory_checks_pass_clean_company():
    dossier = make_sample_dossier(
        status="Active",
        months=48.0,
        offshore=False,
        dissolved_count=0,
        velocity=0.8,
        sic="70229", # Non-risk SIC
        address_line1="100 Commercial Road",
    )
    checks = evaluate_statutory_checks(dossier)
    check_map = {c.id: c.status for c in checks}
    
    assert check_map["ch_status"] == "PASS"
    assert check_map["ch_age"] == "PASS"
    assert check_map["ch_offshore"] == "PASS"
    assert check_map["ch_dissolutions"] == "PASS"
    assert check_map["ch_velocity"] == "PASS"
    assert check_map["ch_address"] == "PASS"

def test_statutory_checks_flag_high_risk_indicators():
    dossier = make_sample_dossier(
        status="Active",
        months=3.0, # < 6 months -> FAIL
        offshore=True, # Offshore BVI -> FAIL
        dissolved_count=3, # 3 dissolutions -> FAIL
        velocity=3.5, # > 3.0/yr -> FAIL
        sic="64999", # High risk SIC -> WARN
        address_line1="Suite 4B, 22 Canary Wharf", # Formation agent -> WARN
    )
    checks = evaluate_statutory_checks(dossier)
    check_map = {c.id: c.status for c in checks}
    
    assert check_map["ch_age"] == "FAIL"
    assert check_map["ch_offshore"] == "FAIL"
    assert check_map["ch_dissolutions"] == "FAIL"
    assert check_map["ch_velocity"] == "FAIL"
    assert check_map["ch_sic"] == "WARN"
    assert check_map["ch_address"] == "WARN"

def test_dimension_scoring_clamps_and_categorizes():
    dossier = make_sample_dossier(
        status="Active",
        months=2.0,
        offshore=True,
        dissolved_count=4,
        velocity=4.0,
    )
    checks = evaluate_statutory_checks(dossier)
    dimensions, overall_score, overall_band = evaluate_risk_dimensions(checks, dossier)
    
    assert overall_score >= 60
    assert overall_band == "HIGH"
    
    for dim in dimensions:
        assert 0 <= dim.score <= 100
        assert dim.band in ("HIGH", "MEDIUM", "LOW")

def test_risk_flags_extraction():
    dossier = make_sample_dossier(
        offshore=True,
        dissolved_count=3,
        sic="64999",
        address_line1="Suite 10, Kemp House",
    )
    checks = evaluate_statutory_checks(dossier)
    flags = extract_risk_flags(dossier, checks)
    
    categories = {f.category for f in flags}
    assert "OFFSHORE_ENTITY" in categories
    assert "DISSOLVED_COMPANY" in categories
    assert "HIGH_RISK_SIC" in categories
    assert "MISMATCH" in categories

"""Builds the Ownership Tree, Related Parties list, and UBO breakdowns from live CompanyDossier.
"""

from typing import List, Tuple, Optional
from app.models.domain import CompanyDossier, PSCEntity
from app.models.dto import (
    OwnershipTreeNodeDTO,
    RelatedPartyDTO,
    UBOBreakdownItemDTO,
)

def psc_to_tree_node(
    psc: PSCEntity,
    child_node: Optional[OwnershipTreeNodeDTO] = None,
    is_root_ubo: bool = False
) -> OwnershipTreeNodeDTO:
    label = psc.ownership_range_label or f"{psc.ownership_pct_estimate}%"
    if is_root_ubo:
        sic_desc = f"Ultimate Beneficial Owner (UBO) · {label} control"
    elif psc.is_offshore:
        sic_desc = f"Offshore Parent ({psc.country_registered or psc.country}) · {label} control"
    elif psc.is_corporate:
        sic_desc = f"Holding Company · {label} control"
    else:
        sic_desc = f"Person with Significant Control · {label} control"
        
    return OwnershipTreeNodeDTO(
        id=f"tree_{psc.id}",
        name=psc.name,
        type="offshore" if psc.is_offshore else ("company" if psc.is_corporate else "person"),
        company_number=psc.registration_number,
        ownership_pct=psc.ownership_pct_estimate,
        risk_band=psc.risk_band,
        status="Active",
        sic_description=sic_desc,
        is_target=False,
        children=[child_node] if child_node else [],
    )

def build_ownership_tree(dossier: CompanyDossier) -> OwnershipTreeNodeDTO:
    """Constructs the visual ownership tree for Tab 2 (Ownership Map).
    Hierarchy: Top UBO / Ultimate Holding Parent -> Intermediate HoldCos -> Target Company.
    Director outside appointments are strictly excluded from ownership hierarchy children.
    """
    # 1. Target node
    target_node = OwnershipTreeNodeDTO(
        id=f"target_{dossier.company_number}",
        name=dossier.company_name,
        type="target",
        company_number=dossier.company_number,
        ownership_pct=100,
        risk_band="HIGH" if dossier.status.lower() != "active" else "LOW",
        status=dossier.status,
        sic_description=dossier.sic_description or "Commercial entity",
        is_target=True,
        children=[],
    )

    # 2. If there are no direct PSCs registered (e.g. widely held listed PLC or no registrable PSC)
    if not dossier.pscs:
        market_label = (
            "Public Market Shareholders (UK Regulated Market · LSE)"
            if dossier.is_exempt_plc
            else "Dispersed Public / Private Shareholders"
        )
        status_label = (
            "Exempt from PSC Register (DTR5)"
            if dossier.is_exempt_plc
            else "No single PSC ≥ 25% registered"
        )
        reason = (
            dossier.psc_exemption_reason
            or "Institutional & Retail Equity Capital Markets (Companies Act 2006 / DTR5)"
        )

        root_node = OwnershipTreeNodeDTO(
            id=f"market_plc_{dossier.company_number}",
            name=market_label,
            type="company",
            company_number=None,
            ownership_pct=100,
            risk_band="LOW",
            status=status_label,
            sic_description=reason,
            is_target=False,
            children=[target_node],
        )
        return root_node

    # 3. If target has PSCs:
    # Pick the primary controlling PSC (one with deepest upstream chain or highest ownership %)
    primary_psc = max(
        dossier.pscs,
        key=lambda p: (len(p.upstream_pscs) * 100) + p.ownership_pct_estimate
    )
    target_node.ownership_pct = primary_psc.ownership_pct_estimate

    # Recursive helper to build chain upwards: Target -> Intermediate HoldCos -> Root UBO
    def walk_up_chain(psc: PSCEntity, current_child: OwnershipTreeNodeDTO) -> OwnershipTreeNodeDTO:
        is_top = len(psc.upstream_pscs) == 0
        node = psc_to_tree_node(psc, current_child, is_root_ubo=is_top and psc.is_natural_person)
        if psc.upstream_pscs:
            top_upstream = max(
                psc.upstream_pscs,
                key=lambda u: (len(u.upstream_pscs) * 100) + u.ownership_pct_estimate
            )
            return walk_up_chain(top_upstream, node)
        return node

    root_tree = walk_up_chain(primary_psc, target_node)

    # If there are other active PSCs that are not in the primary chain,
    # attach them as siblings under an overarching group
    other_pscs = [p for p in dossier.pscs if p.id != primary_psc.id]
    if other_pscs and len(dossier.pscs) > 1:
        group_root = OwnershipTreeNodeDTO(
            id=f"group_{dossier.company_number}",
            name=f"Beneficial Ownership Structure ({len(dossier.pscs)} Registrable PSCs)",
            type="company",
            company_number=None,
            ownership_pct=100,
            risk_band="HIGH" if any(p.is_offshore for p in dossier.pscs) else "LOW",
            status="Active Group Structure",
            sic_description="Controlling Ownership Hierarchy",
            is_target=False,
            children=[
                root_tree,
                *[psc_to_tree_node(p, is_root_ubo=p.is_natural_person) for p in other_pscs]
            ]
        )
        return group_root

    return root_tree

def build_related_parties(dossier: CompanyDossier) -> List[RelatedPartyDTO]:
    """Constructs the related parties list for Tab 3."""
    related: List[RelatedPartyDTO] = []
    
    # Add PSCs
    for psc in dossier.pscs:
        related.append(RelatedPartyDTO(
            name=psc.name,
            type="Company" if psc.is_corporate else "Person",
            relationship=f"PSC with {psc.ownership_range_label} control" + (" (Offshore)" if psc.is_offshore else ""),
            ownership_pct=psc.ownership_pct_estimate,
            shared_directors=[],
            risk_band="HIGH" if psc.is_offshore else ("MEDIUM" if psc.is_corporate else "LOW"),
        ))
        
    # Add connected companies where directors have common directorships
    active_dirs = [d for d in dossier.directors if d.active_appointments > 1]
    added_numbers = set()
    
    for d in active_dirs:
        for appt in d.appointments:
            if appt.company_number != dossier.company_number and appt.company_number not in added_numbers:
                added_numbers.add(appt.company_number)
                
                # Check how many directors share this company
                shared = [dir_obj.name for dir_obj in dossier.directors if any(a.company_number == appt.company_number for a in dir_obj.appointments)]
                
                related.append(RelatedPartyDTO(
                    name=appt.company_name,
                    type="Company",
                    relationship=f"Connected Entity ({appt.status})",
                    ownership_pct=None,
                    shared_directors=shared,
                    risk_band="HIGH" if appt.is_dissolved else "MEDIUM",
                ))
                if len(related) >= 8:
                    break
        if len(related) >= 8:
            break
            
    return related

def build_ubo_breakdown(dossier: CompanyDossier) -> Tuple[List[UBOBreakdownItemDTO], Optional[str]]:
    """Calculates the UBO ownership breakdown progress bars and statutory alert."""
    items: List[UBOBreakdownItemDTO] = []
    has_offshore = False
    
    for psc in dossier.pscs:
        if psc.is_offshore:
            has_offshore = True
        items.append(UBOBreakdownItemDTO(
            name=psc.name,
            pct=psc.ownership_pct_estimate,
        ))
        
    alert = None
    if has_offshore:
        alert = "Offshore entity in ownership chain. Natural person UBO unidentifiable. EDD required under MLR 2017."
    elif not dossier.pscs and not dossier.is_exempt_plc:
        alert = "No PSCs registered on Companies House. Beneficial ownership could not be verified."
    elif all(p.is_corporate for p in dossier.pscs):
        alert = "Only corporate entities registered as PSC. Intermediate holding structure requires verification."
        
    return items, alert

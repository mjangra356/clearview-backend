"""Reference datasets for Fraud & Compliance rule evaluations.

Sourced from FATF high-risk jurisdictions, UK JMLSG AML Guidance,
and UK corporate formation typologies.
"""

from typing import Dict, Set, List

# Tax havens and offshore secrecy jurisdictions
OFFSHORE_JURISDICTIONS: Set[str] = {
    "British Virgin Islands",
    "Virgin Islands, British",
    "Cayman Islands",
    "Seychelles",
    "Belize",
    "Panama",
    "Isle of Man",
    "Jersey",
    "Guernsey",
    "Marshall Islands",
    "Liechtenstein",
    "Andorra",
    "Monaco",
    "Vanuatu",
    "Cook Islands",
    "Bahamas",
    "Bermuda",
    "Gibraltar",
    "Saint Kitts and Nevis",
}

# High-risk Standard Industrial Classification (SIC) codes under JMLSG / FATF guidance
HIGH_RISK_SICS: Dict[str, str] = {
    "64999": "Financial services NEC (unregulated)",
    "64205": "Financial holding companies",
    "64191": "Banks",
    "66190": "Auxiliary financial services (crypto-adjacent)",
    "66120": "Securities dealing",
    "66110": "Stock exchange activities",
    "92000": "Gambling & betting",
    "56302": "Public houses & bars (cash-intensive)",
    "45111": "Sale of new cars",
    "45112": "Sale of used cars",
    "68100": "Real estate (own property)",
    "68209": "Letting of own property",
    "68320": "Real estate management",
    "47770": "Jewellery & precious stones retail",
    "24410": "Precious metals production",
    "38320": "Recovery of sorted materials (cash-intensive)",
}

# Formation agent / virtual office / mail-drop indicators in registered addresses
FORMATION_AGENT_KEYWORDS: List[str] = [
    "formations house",
    "companies made simple",
    "suite",
    "flat",
    "unit",
    "c/o",
    "kemp house",
    "shelton street",
    "regus",
    "mailbox",
    "serviced offices",
]

# Nationalities under FATF increased monitoring / high-risk jurisdictions
FATF_HIGH_RISK_NATIONALITIES: Set[str] = {
    "Russian",
    "Belarusian",
    "Iranian",
    "North Korean",
    "Syrian",
    "Venezuelan",
    "Nicaraguan",
    "Burmese",
    "Myanmar",
}

"""
MADMIN Geo-IP data service.

Downloads per-country aggregated CIDR lists from ipdeny.com and caches them on
disk. This module is a pure *data provider*: it exposes the ISO country catalog
and the per-country CIDR lists (country_cidrs), which core.firewall.addresses
uses to materialize geo-type address objects under the uniform MADMIN_AO_<ref_key>
naming. geoip itself no longer owns or names any ipset.

Design goals:
- No new pip dependency (uses stdlib urllib).
- Fail-soft: download/network errors never raise and never empty an in-use ipset
  (the last good cached zone file is kept and reused).
- mock_iptables aware: skips real ipset commands in development.
"""
import logging
import re
import urllib.request
from pathlib import Path
from typing import List, Optional, Dict, Tuple

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

GEO_CACHE_DIR = Path(settings.data_dir) / "geoip"
IPDENY_URL = "https://www.ipdeny.com/ipblocks/data/aggregated/{cc}-aggregated.zone"
_DOWNLOAD_TIMEOUT = 30
_CIDR_RE = re.compile(r'^\d{1,3}(?:\.\d{1,3}){3}/\d{1,2}$')

# Full ISO 3166-1 alpha-2 mapping (code -> English short name)
# Source: ISO list + commonly used short names
ISO_COUNTRIES: Dict[str, str] = {
    "AF": "Afghanistan",
    "AX": "Åland Islands",
    "AL": "Albania",
    "DZ": "Algeria",
    "AS": "American Samoa",
    "AD": "Andorra",
    "AO": "Angola",
    "AI": "Anguilla",
    "AQ": "Antarctica",
    "AG": "Antigua and Barbuda",
    "AR": "Argentina",
    "AM": "Armenia",
    "AW": "Aruba",
    "AU": "Australia",
    "AT": "Austria",
    "AZ": "Azerbaijan",
    "BS": "Bahamas",
    "BH": "Bahrain",
    "BD": "Bangladesh",
    "BB": "Barbados",
    "BY": "Belarus",
    "BE": "Belgium",
    "BZ": "Belize",
    "BJ": "Benin",
    "BM": "Bermuda",
    "BT": "Bhutan",
    "BO": "Bolivia (Plurinational State of)",
    "BQ": "Bonaire, Sint Eustatius and Saba",
    "BA": "Bosnia and Herzegovina",
    "BW": "Botswana",
    "BV": "Bouvet Island",
    "BR": "Brazil",
    "IO": "British Indian Ocean Territory",
    "BN": "Brunei Darussalam",
    "BG": "Bulgaria",
    "BF": "Burkina Faso",
    "BI": "Burundi",
    "CV": "Cabo Verde",
    "KH": "Cambodia",
    "CM": "Cameroon",
    "CA": "Canada",
    "KY": "Cayman Islands",
    "CF": "Central African Republic",
    "TD": "Chad",
    "CL": "Chile",
    "CN": "China",
    "CX": "Christmas Island",
    "CC": "Cocos (Keeling) Islands",
    "CO": "Colombia",
    "KM": "Comoros",
    "CG": "Congo",
    "CD": "Congo, Democratic Republic of the",
    "CK": "Cook Islands",
    "CR": "Costa Rica",
    "CI": "Côte d'Ivoire",
    "HR": "Croatia",
    "CU": "Cuba",
    "CW": "Curaçao",
    "CY": "Cyprus",
    "CZ": "Czechia",
    "DK": "Denmark",
    "DJ": "Djibouti",
    "DM": "Dominica",
    "DO": "Dominican Republic",
    "EC": "Ecuador",
    "EG": "Egypt",
    "SV": "El Salvador",
    "GQ": "Equatorial Guinea",
    "ER": "Eritrea",
    "EE": "Estonia",
    "SZ": "Eswatini",
    "ET": "Ethiopia",
    "FK": "Falkland Islands (Malvinas)",
    "FO": "Faroe Islands",
    "FJ": "Fiji",
    "FI": "Finland",
    "FR": "France",
    "GF": "French Guiana",
    "PF": "French Polynesia",
    "TF": "French Southern Territories",
    "GA": "Gabon",
    "GM": "Gambia",
    "GE": "Georgia",
    "DE": "Germany",
    "GH": "Ghana",
    "GI": "Gibraltar",
    "GR": "Greece",
    "GL": "Greenland",
    "GD": "Grenada",
    "GP": "Guadeloupe",
    "GU": "Guam",
    "GT": "Guatemala",
    "GG": "Guernsey",
    "GN": "Guinea",
    "GW": "Guinea-Bissau",
    "GY": "Guyana",
    "HT": "Haiti",
    "HM": "Heard Island and McDonald Islands",
    "VA": "Holy See",
    "HN": "Honduras",
    "HK": "Hong Kong",
    "HU": "Hungary",
    "IS": "Iceland",
    "IN": "India",
    "ID": "Indonesia",
    "IR": "Iran (Islamic Republic of)",
    "IQ": "Iraq",
    "IE": "Ireland",
    "IM": "Isle of Man",
    "IL": "Israel",
    "IT": "Italy",
    "JM": "Jamaica",
    "JP": "Japan",
    "JE": "Jersey",
    "JO": "Jordan",
    "KZ": "Kazakhstan",
    "KE": "Kenya",
    "KI": "Kiribati",
    "KP": "Korea (Democratic People's Republic of)",
    "KR": "Korea, Republic of",
    "KW": "Kuwait",
    "KG": "Kyrgyzstan",
    "LA": "Lao People's Democratic Republic",
    "LV": "Latvia",
    "LB": "Lebanon",
    "LS": "Lesotho",
    "LR": "Liberia",
    "LY": "Libya",
    "LI": "Liechtenstein",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "MO": "Macao",
    "MG": "Madagascar",
    "MW": "Malawi",
    "MY": "Malaysia",
    "MV": "Maldives",
    "ML": "Mali",
    "MT": "Malta",
    "MH": "Marshall Islands",
    "MQ": "Martinique",
    "MR": "Mauritania",
    "MU": "Mauritius",
    "YT": "Mayotte",
    "MX": "Mexico",
    "FM": "Micronesia (Federated States of)",
    "MD": "Moldova, Republic of",
    "MC": "Monaco",
    "MN": "Mongolia",
    "ME": "Montenegro",
    "MS": "Montserrat",
    "MA": "Morocco",
    "MZ": "Mozambique",
    "MM": "Myanmar",
    "NA": "Namibia",
    "NR": "Nauru",
    "NP": "Nepal",
    "NL": "Netherlands",
    "NC": "New Caledonia",
    "NZ": "New Zealand",
    "NI": "Nicaragua",
    "NE": "Niger",
    "NG": "Nigeria",
    "NU": "Niue",
    "NF": "Norfolk Island",
    "MK": "North Macedonia",
    "MP": "Northern Mariana Islands",
    "NO": "Norway",
    "OM": "Oman",
    "PK": "Pakistan",
    "PW": "Palau",
    "PS": "Palestine, State of",
    "PA": "Panama",
    "PG": "Papua New Guinea",
    "PY": "Paraguay",
    "PE": "Peru",
    "PH": "Philippines",
    "PN": "Pitcairn",
    "PL": "Poland",
    "PT": "Portugal",
    "PR": "Puerto Rico",
    "QA": "Qatar",
    "RE": "Réunion",
    "RO": "Romania",
    "RU": "Russian Federation",
    "RW": "Rwanda",
    "BL": "Saint Barthélemy",
    "SH": "Saint Helena, Ascension and Tristan da Cunha",
    "KN": "Saint Kitts and Nevis",
    "LC": "Saint Lucia",
    "MF": "Saint Martin (French part)",
    "PM": "Saint Pierre and Miquelon",
    "VC": "Saint Vincent and the Grenadines",
    "WS": "Samoa",
    "SM": "San Marino",
    "ST": "Sao Tome and Principe",
    "SA": "Saudi Arabia",
    "SN": "Senegal",
    "RS": "Serbia",
    "SC": "Seychelles",
    "SL": "Sierra Leone",
    "SG": "Singapore",
    "SX": "Sint Maarten (Dutch part)",
    "SK": "Slovakia",
    "SI": "Slovenia",
    "SB": "Solomon Islands",
    "SO": "Somalia",
    "ZA": "South Africa",
    "GS": "South Georgia and the South Sandwich Islands",
    "SS": "South Sudan",
    "ES": "Spain",
    "LK": "Sri Lanka",
    "SD": "Sudan",
    "SR": "Suriname",
    "SJ": "Svalbard and Jan Mayen",
    "SE": "Sweden",
    "CH": "Switzerland",
    "SY": "Syrian Arab Republic",
    "TW": "Taiwan, Province of China",
    "TJ": "Tajikistan",
    "TZ": "Tanzania, United Republic of",
    "TH": "Thailand",
    "TL": "Timor-Leste",
    "TG": "Togo",
    "TK": "Tokelau",
    "TO": "Tonga",
    "TT": "Trinidad and Tobago",
    "TN": "Tunisia",
    "TR": "Turkey",
    "TM": "Turkmenistan",
    "TC": "Turks and Caicos Islands",
    "TV": "Tuvalu",
    "UG": "Uganda",
    "UA": "Ukraine",
    "AE": "United Arab Emirates",
    "GB": "United Kingdom of Great Britain and Northern Ireland",
    "UM": "United States Minor Outlying Islands",
    "US": "United States of America",
    "UY": "Uruguay",
    "UZ": "Uzbekistan",
    "VU": "Vanuatu",
    "VE": "Venezuela (Bolivarian Republic of)",
    "VN": "Viet Nam",
    "VG": "Virgin Islands (British)",
    "VI": "Virgin Islands (U.S.)",
    "WF": "Wallis and Futuna",
    "EH": "Western Sahara",
    "YE": "Yemen",
    "ZM": "Zambia",
    "ZW": "Zimbabwe",
}


def country_name(cc: str) -> Optional[str]:
    """Return the English short name for ISO alpha-2 code `cc`, or None."""
    if not cc:
        return None
    return ISO_COUNTRIES.get(cc.upper())


def is_valid_country_code(cc: str) -> bool:
    """Validate an ISO 3166-1 alpha-2 country code (case-insensitive)."""
    if not cc:
        return False
    return cc.upper() in ISO_COUNTRIES


def country_choices() -> List[Tuple[str, str]]:
    """Return a list of `(code, name)` tuples sorted by country name for dropdowns."""
    return sorted(ISO_COUNTRIES.items(), key=lambda it: it[1])


def _cache_file(cc: str) -> Path:
    return GEO_CACHE_DIR / f"{cc}.zone"


def _read_cached_cidrs(cc: str) -> List[str]:
    """Read and validate CIDRs from a cached zone file. Returns [] if missing/empty."""
    path = _cache_file(cc)
    if not path.exists():
        return []
    try:
        lines = path.read_text().splitlines()
    except OSError as e:
        logger.warning(f"Geo: failed to read cache for {cc}: {e}")
        return []
    return [ln.strip() for ln in lines if _CIDR_RE.match(ln.strip())]


def download_country(cc: str) -> bool:
    """
    Download the aggregated CIDR zone for a country and cache it on disk.

    Fail-soft: on any error the existing cache file (if any) is left untouched
    and False is returned. Only overwrites the cache when a non-empty, valid
    list is fetched.
    """
    cc = cc.lower()
    url = IPDENY_URL.format(cc=cc)
    try:
        GEO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "madmin-geoip"})
        with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        logger.warning(f"Geo: download failed for {cc} ({url}): {e}; keeping cached copy")
        return False

    cidrs = [ln.strip() for ln in raw.splitlines() if _CIDR_RE.match(ln.strip())]
    if not cidrs:
        logger.warning(f"Geo: download for {cc} returned no valid CIDRs; keeping cached copy")
        return False

    try:
        _cache_file(cc).write_text("\n".join(cidrs) + "\n")
        logger.info(f"Geo: cached {len(cidrs)} CIDRs for {cc}")
        return True
    except OSError as e:
        logger.error(f"Geo: failed to write cache for {cc}: {e}")
        return False


def country_cidrs(cc: str, force_reload: bool = False) -> List[str]:
    """
    Return the aggregated CIDR list for a country, downloading + caching it on
    first use (or when force_reload is True). Fail-soft: on download error the
    last good cached copy is reused; returns [] only if nothing is available.

    This is the data-provider entry point used by core.firewall.addresses to
    materialize geo-type address objects under the uniform MADMIN_AO_<ref_key>
    naming. geoip no longer owns any ipset — it only provides country data.
    """
    cc = cc.lower()
    if force_reload or not _cache_file(cc).exists():
        download_country(cc)
    return _read_cached_cidrs(cc)

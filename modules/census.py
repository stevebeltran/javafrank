"""Census population data lookups and utilities."""
import streamlit as st
import re
import json
import urllib.request
from modules.config import STATE_FIPS, KNOWN_POPULATIONS

_PLACE_SUFFIXES = (
    ' city', ' town', ' village', ' borough', ' township', ' cdp', ' municipality',
    ' county', ' parish', ' census area', ' city and borough', ' borough county',
    ' urban county', ' unified government', ' metro government',
)


def _normalize_population_lookup_name(value):
    text = str(value or '').strip().lower()
    text = text.replace('&', ' and ')
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    for suffix in _PLACE_SUFFIXES:
        if text.endswith(suffix):
            text = text[:-len(suffix)].strip()
            break
    return text


def _population_lookup_aliases(value):
    base = _normalize_population_lookup_name(value)
    aliases = {base} if base else set()
    if not base:
        return aliases
    aliases.add(base.replace('saint ', 'st '))
    aliases.add(base.replace('st ', 'saint '))
    aliases.add(base.replace('-', ' '))
    aliases.add(base.replace('saint ', 'st ').replace('-', ' '))
    aliases.add(base.replace('st ', 'saint ').replace('-', ' '))
    return {alias.strip() for alias in aliases if alias.strip()}


def _lookup_known_population(place_name):
    direct = KNOWN_POPULATIONS.get(place_name)
    if direct is not None:
        return direct
    aliases = _population_lookup_aliases(place_name)
    for known_name, pop in KNOWN_POPULATIONS.items():
        if _normalize_population_lookup_name(known_name) in aliases:
            return pop
    return None


def _lookup_population_for_boundary(state_abbr, city_name, boundary_kind='place'):
    state_fips = STATE_FIPS.get(str(state_abbr or '').strip().upper(), '')
    if not state_fips:
        return None
    if boundary_kind == 'state':
        return fetch_census_state_population(state_fips)
    lookup_name = city_name or state_abbr
    return fetch_census_population(state_fips, lookup_name, is_county=(boundary_kind == 'county'))


def _refresh_reference_population(session_state, selected_names=None):
    state_abbr = str(session_state.get('active_state', '') or '').strip().upper()
    boundary_kind = str(session_state.get('boundary_kind', 'place') or 'place').strip().lower()
    if session_state.get('use_county_boundary'):
        boundary_kind = 'county'

    targets = []
    for name in (selected_names or []):
        clean_name = str(name or '').strip()
        if clean_name and clean_name not in targets:
            targets.append(clean_name)

    if not targets:
        fallback_name = session_state.get('active_city') or session_state.get('active_state') or ''
        fallback_name = str(fallback_name or '').strip()
        if fallback_name:
            targets.append(fallback_name)

    total_population = 0
    all_targets_resolved = bool(targets)

    if boundary_kind == 'state':
        resolved = _lookup_population_for_boundary(state_abbr, state_abbr, boundary_kind='state')
        total_population = int(resolved or 0)
        all_targets_resolved = bool(resolved)
    elif state_abbr and targets:
        for target_name in targets:
            resolved = _lookup_population_for_boundary(
                state_abbr,
                target_name,
                boundary_kind=boundary_kind,
            )
            if resolved:
                total_population += int(resolved)
            else:
                all_targets_resolved = False
    else:
        all_targets_resolved = False

    session_state['estimated_pop'] = int(total_population or 0)
    session_state['_pop_resolved'] = bool(total_population) and all_targets_resolved
    session_state['population_reference_kind'] = boundary_kind
    session_state['population_reference_targets'] = targets
    return int(total_population or 0)


@st.cache_data
def fetch_census_population(state_fips, place_name, is_county=False):
    if is_county:
        url = f"https://api.census.gov/data/2020/dec/pl?get=P1_001N,NAME&for=county:*&in=state:{state_fips}"
    else:
        url = f"https://api.census.gov/data/2020/dec/pl?get=P1_001N,NAME&for=place:*&in=state:{state_fips}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode('utf-8'))
            search_aliases = _population_lookup_aliases(place_name)
            exact_match = None
            prefix_match = None
            for row in data[1:]:
                place_full = str(row[1]).split(',')[0].strip()
                place_aliases = _population_lookup_aliases(place_full)
                if search_aliases & place_aliases:
                    exact_match = int(row[0])
                    break
                for search_name in search_aliases:
                    if any(
                        alias.startswith(search_name + ' ')
                        or alias.startswith(search_name + '-')
                        for alias in place_aliases
                    ):
                        prefix_match = int(row[0])
                        break
                if prefix_match is not None:
                    break
            if exact_match is not None:
                return exact_match
            if prefix_match is not None:
                return prefix_match
    except Exception:
        pass
    return _lookup_known_population(place_name)

@st.cache_data
def fetch_census_state_population(state_fips):
    url = f"https://api.census.gov/data/2020/dec/pl?get=P1_001N,NAME&for=state:{state_fips}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            if len(data) > 1 and len(data[1]) > 0:
                return int(data[1][0])
    except Exception:
        pass
    return None

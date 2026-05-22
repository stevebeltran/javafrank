"""
Geocoding module for address and facility lookups.
Handles forward geocoding, reverse geocoding, and public facility searches.
"""
import streamlit as st
import pandas as pd
import os
import re
import json
import urllib.request
import urllib.parse
import hashlib
import concurrent.futures as cf
from concurrent.futures import ThreadPoolExecutor

from modules.config import US_STATES_ABBR


def get_address_from_latlon(lat, lon):
    url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=18&addressdetails=1"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'BRINC_DFR_Optimizer_App/2.0'})
        with urllib.request.urlopen(req, timeout=2) as response:
            data = json.loads(response.read().decode('utf-8'))
            if 'address' in data:
                addr = data['address']
                road = addr.get('road', '')
                house_number = addr.get('house_number', '')
                city = addr.get('city', addr.get('town', addr.get('village', '')))
                if road:
                    return f"{house_number} {road}, {city}".strip(', ')
    except Exception:
        pass
    # Fallback to coordinates if an exact street address isn't found
    return f"{lat:.5f}, {lon:.5f}"

def _lookup_streamlit_secret(*names):
    _target_names = {str(_name or '').strip().upper() for _name in names if str(_name or '').strip()}
    if not _target_names:
        return ""

    def _scan_secret_container(_container, _visited=None):
        _visited = _visited or set()
        _obj_id = id(_container)
        if _obj_id in _visited:
            return ""
        _visited.add(_obj_id)

        if hasattr(_container, 'items'):
            try:
                _items = list(_container.items())
            except Exception:
                _items = []

            for _key, _value in _items:
                if str(_key or '').strip().upper() in _target_names and not hasattr(_value, 'items'):
                    _secret_value = str(_value or '').strip()
                    if _secret_value:
                        return _secret_value

            for _, _value in _items:
                if hasattr(_value, 'items'):
                    _nested_value = _scan_secret_container(_value, _visited)
                    if _nested_value:
                        return _nested_value
        return ""

    try:
        _secret_value = _scan_secret_container(st.secrets)
        if _secret_value:
            return _secret_value
    except Exception:
        pass

    for _name in names:
        _env_value = str(os.environ.get(str(_name or '').strip(), '') or '').strip()
        if _env_value:
            return _env_value
    return ""


def _get_google_maps_api_key():
    return _lookup_streamlit_secret(
        "GOOGLE_MAPS_API_KEY",
        "GOOGLE_GEOCODING_API_KEY",
        "GOOGLE_API_KEY",
        "GMAPS_API_KEY",
    )


def _get_mapbox_api_key():
    return _lookup_streamlit_secret(
        "MAPBOX_ACCESS_TOKEN",
        "MAPBOX_API_KEY",
        "MAPBOX_TOKEN",
    )


def _get_geocoder_provider_signature():
    _provider_values = {
        'google': _get_google_maps_api_key(),
        'mapbox': _get_mapbox_api_key(),
    }
    _signature_payload = "|".join(
        f"{_provider}:{hashlib.sha256(str(_value or '').encode('utf-8')).hexdigest()}"
        for _provider, _value in sorted(_provider_values.items())
    )
    return hashlib.sha256(_signature_payload.encode('utf-8')).hexdigest()


@st.cache_data(show_spinner=False)
def _search_address_candidates_cached(address_str, limit=6, preferred_city="", preferred_state="", provider_signature=""):
    address_str = str(address_str or '').strip()
    if not address_str:
        try:
            st.session_state['_last_geocode_trace'] = {
                'input': '',
                'preferred_city': str(preferred_city or '').strip(),
                'preferred_state': str(preferred_state or '').strip().upper(),
                'queries': [],
                'providers': [],
                'candidate_count': 0,
            }
        except Exception:
            pass
        return []

    limit = max(1, min(int(limit or 6), 10))
    preferred_city = str(preferred_city or '').strip()
    preferred_state = str(preferred_state or '').strip().upper()
    # Full state name for providers (OSM) that return "Nebraska" instead of "NE"
    _abbr_to_full = {v: k for k, v in US_STATES_ABBR.items()}
    preferred_state_full = _abbr_to_full.get(preferred_state, '').lower()
    candidates = []
    seen = set()

    def _normalize_text(value):
        return str(value or "").strip().lower()

    def _normalize_address_variants(raw_value):
        raw_value = str(raw_value or '').strip()
        if not raw_value:
            return []
        variants = [raw_value]
        compact = re.sub(r'\s+', ' ', raw_value).strip()
        if compact and compact.lower() != raw_value.lower():
            variants.append(compact)

        word_to_num = {
            'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5',
            'six': '6', 'seven': '7', 'eight': '8', 'nine': '9', 'ten': '10',
        }
        street_suffix_map = {
            'street': 'st',
            'avenue': 'ave',
            'boulevard': 'blvd',
            'road': 'rd',
            'drive': 'dr',
            'lane': 'ln',
            'court': 'ct',
            'place': 'pl',
            'parkway': 'pkwy',
            'circle': 'cir',
            'terrace': 'ter',
        }

        def _transform_variant(text):
            text = re.sub(r'\s+', ' ', str(text or '').strip())
            if not text:
                return []
            out = [text]
            parts = text.split(' ', 1)
            if parts:
                first = parts[0].lower().rstrip('.,')
                if first in word_to_num and len(parts) > 1:
                    out.append(f"{word_to_num[first]} {parts[1]}")
            replaced = text
            for suffix, abbr in street_suffix_map.items():
                replaced = re.sub(rf'\b{suffix}\b', abbr, replaced, flags=re.IGNORECASE)
            if replaced.lower() != text.lower():
                out.append(replaced)
            out2 = []
            for candidate in out:
                parts2 = candidate.split(' ', 1)
                if parts2:
                    first2 = parts2[0].lower().rstrip('.,')
                    if first2 in word_to_num and len(parts2) > 1:
                        candidate = f"{word_to_num[first2]} {parts2[1]}"
                replaced2 = candidate
                for suffix, abbr in street_suffix_map.items():
                    replaced2 = re.sub(rf'\b{suffix}\b', abbr, replaced2, flags=re.IGNORECASE)
                out2.append(candidate)
                if replaced2.lower() != candidate.lower():
                    out2.append(replaced2)
            deduped = []
            seen_local = set()
            for candidate in out2:
                cleaned = re.sub(r'\s+', ' ', str(candidate or '').strip())
                key = cleaned.lower()
                if cleaned and key not in seen_local:
                    seen_local.add(key)
                    deduped.append(cleaned)
            return deduped

        expanded = []
        seen_expanded = set()
        for variant in variants:
            for candidate in _transform_variant(variant):
                key = candidate.lower()
                if candidate and key not in seen_expanded:
                    seen_expanded.add(key)
                    expanded.append(candidate)
        return expanded

    def _query_variants():
        _variants = []
        for _base_variant in _normalize_address_variants(address_str):
            _variants.append(_base_variant)
            _has_city = preferred_city and preferred_city.lower() in _base_variant.lower()
            _has_state = preferred_state and preferred_state.lower() in _base_variant.lower()
            if preferred_city and preferred_state and (not _has_city or not _has_state):
                _variants.append(f"{_base_variant}, {preferred_city}, {preferred_state}")
            if preferred_state and not _has_state:
                _variants.append(f"{_base_variant}, {preferred_state}")
        ordered = []
        seen_variants = set()
        for _variant in _variants:
            _clean = str(_variant or '').strip()
            if _clean and _clean.lower() not in seen_variants:
                seen_variants.add(_clean.lower())
                ordered.append(_clean)
        return ordered

    def _candidate_score(candidate):
        _label = _normalize_text(candidate.get('matched_address') or candidate.get('label'))
        _source = str(candidate.get('source', ''))
        _score = {
            'Google': 500,
            'Mapbox': 425,
            'Census': 350,
            'OSM': 250,
        }.get(_source, 0)

        if preferred_state:
            _state_token = f", {preferred_state.lower()}"
            _full_token = f", {preferred_state_full}" if preferred_state_full else None
            _in_label = (
                _state_token in _label
                or _label.endswith(f" {preferred_state.lower()}")
                or (_full_token and _full_token in _label)
            )
            if _in_label:
                _score += 220
            else:
                _score -= 180
        if preferred_city:
            if preferred_city.lower() in _label:
                _score += 150
            else:
                _score -= 80

        _typed = _normalize_text(address_str)
        if _typed and _typed in _label:
            _score += 80
        elif _typed:
            _score += max(0, 30 - min(len(_typed), 30))
        return _score

    def _add_candidate(label, lat, lon, source, raw_match=''):
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except Exception:
            return
        dedupe_key = (round(lat_f, 6), round(lon_f, 6), str(label).strip().lower())
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
        candidates.append({
            'label': str(label).strip() or str(raw_match).strip() or address_str,
            'matched_address': str(raw_match).strip() or str(label).strip() or address_str,
            'lat': lat_f,
            'lon': lon_f,
            'source': source,
            '_score': 0,
        })

    _queries = _query_variants()
    _provider_trace = []

    for _query in _queries:
        try:
            _params = urllib.parse.urlencode({
                'address': _query,
                'benchmark': '2020',
                'format': 'json'
            })
            _url = f"https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?{_params}"
            _req = urllib.request.Request(_url, headers={'User-Agent': 'BRINC_COS_Optimizer/1.0'})
            with urllib.request.urlopen(_req, timeout=8) as _resp:
                _data = json.loads(_resp.read().decode('utf-8'))
            _matches = _data.get('result', {}).get('addressMatches', [])[:limit]
            _provider_trace.append({'provider': 'Census', 'query': _query, 'used': True, 'match_count': len(_matches), 'status': 'ok'})
            for _match in _matches:
                _coords = _match.get('coordinates', {})
                _add_candidate(
                    _match.get('matchedAddress', _query),
                    _coords.get('y'),
                    _coords.get('x'),
                    'Census',
                    raw_match=_match.get('matchedAddress', _query),
                )
        except Exception:
            _provider_trace.append({'provider': 'Census', 'query': _query, 'used': True, 'match_count': 0, 'status': 'error'})

    _google_api_key = _get_google_maps_api_key()
    if _google_api_key:
        for _query in _queries:
            try:
                _params = urllib.parse.urlencode({
                    'address': _query,
                    'key': _google_api_key,
                    'components': f'country:US|administrative_area:{preferred_state}' if preferred_state else 'country:US',
                })
                _url = f"https://maps.googleapis.com/maps/api/geocode/json?{_params}"
                _req = urllib.request.Request(_url, headers={'User-Agent': 'BRINC_COS_Optimizer/1.0'})
                with urllib.request.urlopen(_req, timeout=8) as _resp:
                    _data = json.loads(_resp.read().decode('utf-8'))
                _matches = _data.get('results', [])[:limit]
                _provider_trace.append({'provider': 'Google', 'query': _query, 'used': True, 'match_count': len(_matches), 'status': _data.get('status', 'ok')})
                for _match in _matches:
                    _geometry = _match.get('geometry', {}).get('location', {})
                    _label = _match.get('formatted_address', _query)
                    _add_candidate(_label, _geometry.get('lat'), _geometry.get('lng'), 'Google', raw_match=_label)
            except Exception:
                _provider_trace.append({'provider': 'Google', 'query': _query, 'used': True, 'match_count': 0, 'status': 'error'})
    else:
        _provider_trace.append({'provider': 'Google', 'query': '', 'used': False, 'match_count': 0, 'status': 'missing_api_key'})

    _mapbox_key = _get_mapbox_api_key()
    if _mapbox_key:
        for _query in _queries:
            try:
                _params = urllib.parse.urlencode({
                    'q': _query,
                    'access_token': _mapbox_key,
                    'country': 'US',
                    'limit': str(limit),
                    'autocomplete': 'true',
                    'types': 'address,street',
                })
                _url = f"https://api.mapbox.com/search/geocode/v6/forward?{_params}"
                _req = urllib.request.Request(_url, headers={'User-Agent': 'BRINC_COS_Optimizer/1.0'})
                with urllib.request.urlopen(_req, timeout=8) as _resp:
                    _data = json.loads(_resp.read().decode('utf-8'))
                _matches = _data.get('features', [])[:limit]
                _provider_trace.append({'provider': 'Mapbox', 'query': _query, 'used': True, 'match_count': len(_matches), 'status': 'ok'})
                for _match in _matches:
                    _coords = (_match.get('geometry') or {}).get('coordinates') or [None, None]
                    _props = _match.get('properties') or {}
                    _label = (
                        _props.get('full_address')
                        or _match.get('place_name')
                        or _match.get('name')
                        or _query
                    )
                    _add_candidate(_label, _coords[1], _coords[0], 'Mapbox', raw_match=_label)
            except Exception:
                _provider_trace.append({'provider': 'Mapbox', 'query': _query, 'used': True, 'match_count': 0, 'status': 'error'})
    else:
        _provider_trace.append({'provider': 'Mapbox', 'query': '', 'used': False, 'match_count': 0, 'status': 'missing_api_key'})

    for _query in _queries:
        try:
            _params = urllib.parse.urlencode({
                'format': 'jsonv2',
                'q': _query,
                'limit': str(limit),
                'countrycodes': 'us',
                'addressdetails': '1',
            })
            _url = f"https://nominatim.openstreetmap.org/search?{_params}"
            _req = urllib.request.Request(_url, headers={'User-Agent': 'BRINC_COS_Optimizer/1.0'})
            with urllib.request.urlopen(_req, timeout=8) as _resp:
                _data = json.loads(_resp.read().decode('utf-8'))
            _matches = _data[:limit]
            _provider_trace.append({'provider': 'OSM', 'query': _query, 'used': True, 'match_count': len(_matches), 'status': 'ok'})
            for _match in _matches:
                _label = _match.get('display_name', _query)
                _add_candidate(_label, _match.get('lat'), _match.get('lon'), 'OSM', raw_match=_label)
        except Exception:
            _provider_trace.append({'provider': 'OSM', 'query': _query, 'used': True, 'match_count': 0, 'status': 'error'})

    for _candidate in candidates:
        _candidate['_score'] = _candidate_score(_candidate)
    candidates.sort(key=lambda _item: (-_item.get('_score', 0), _item.get('matched_address', '')))
    try:
        st.session_state['_last_geocode_trace'] = {
            'input': address_str,
            'preferred_city': preferred_city,
            'preferred_state': preferred_state,
            'queries': _queries,
            'providers': _provider_trace,
            'candidate_count': len(candidates),
            'top_candidate': candidates[0]['matched_address'] if candidates else '',
        }
    except Exception:
        pass
    return [{k: v for k, v in _candidate.items() if k != '_score'} for _candidate in candidates[:limit]]


def search_address_candidates(address_str, limit=6, preferred_city="", preferred_state=""):
    return _search_address_candidates_cached(
        address_str,
        limit=limit,
        preferred_city=preferred_city,
        preferred_state=preferred_state,
        provider_signature=_get_geocoder_provider_signature(),
    )

_PUBLIC_FACILITY_QUERY_TERMS = {
    'Police': ['police department', 'police station', 'sheriff office', 'public safety'],
    'Fire': ['fire station', 'fire department', 'fire hall', 'rescue station'],
    'School': ['school', 'elementary school', 'middle school', 'high school', 'academy'],
    'Government': ['city hall', 'town hall', 'public works', 'municipal building', 'municipal services', 'government center', 'civic center'],
    'Library': ['library', 'public library', 'library branch'],
}

def _normalize_public_facility_type(facility_type):
    raw = str(facility_type or '').strip().lower()
    if not raw:
        return ''
    if 'police' in raw or 'law enforcement' in raw or 'sheriff' in raw:
        return 'Police'
    if 'fire' in raw or 'ems' in raw or 'ambulance' in raw or 'rescue' in raw:
        return 'Fire'
    if 'school' in raw or 'academy' in raw:
        return 'School'
    if 'library' in raw:
        return 'Library'
    if 'government' in raw or 'public works' in raw or 'city hall' in raw or 'town hall' in raw or 'municipal' in raw or 'civic' in raw:
        return 'Government'
    return ''


def _looks_like_street_address(text):
    raw = str(text or '').strip().lower()
    if not raw:
        return False
    if not re.search(r'\d', raw):
        return False
    street_tokens = (
        ' st', ' street', ' rd', ' road', ' ave', ' avenue', ' blvd', ' boulevard',
        ' dr', ' drive', ' ln', ' lane', ' ct', ' court', ' pkwy', ' parkway',
        ' hwy', ' highway', ' ter', ' terrace', ' cir', ' circle', ' way', ' pl',
        ' place', ' n ', ' s ', ' e ', ' w ',
    )
    return any(token in raw for token in street_tokens)


def _public_facility_query_variants(query_str, facility_type, preferred_city="", preferred_state=""):
    query_str = str(query_str or '').strip()
    if not query_str:
        return []

    facility_key = _normalize_public_facility_type(facility_type)
    terms = _PUBLIC_FACILITY_QUERY_TERMS.get(facility_key, [])
    if not terms:
        return []

    preferred_city = str(preferred_city or '').strip()
    preferred_state = str(preferred_state or '').strip().upper()
    variants = []

    base_queries = [query_str]
    _lower_query = query_str.lower()
    if preferred_city and preferred_state and preferred_city.lower() not in _lower_query and preferred_state.lower() not in _lower_query:
        base_queries.append(f"{query_str}, {preferred_city}, {preferred_state}")

    for base_query in base_queries:
        for term in terms:
            variants.append(f"{base_query}, {term}")
            variants.append(f"{base_query} {term}")

    ordered = []
    seen = set()
    for variant in variants:
        clean = re.sub(r'\s+', ' ', str(variant or '').strip())
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            ordered.append(clean)
    return ordered


def _public_facility_type_is_plausible(feature_type, facility_key):
    feature_type = str(feature_type or '').strip().lower()
    if not feature_type:
        return False
    if facility_key == 'Fire':
        return feature_type == 'fire_station'
    if facility_key == 'Police':
        return feature_type in {'police', 'police_station', 'public_bldg'}
    if facility_key == 'School':
        return feature_type in {'school', 'college', 'university'}
    if facility_key == 'Library':
        return feature_type == 'library'
    if facility_key == 'Government':
        return feature_type in {'townhall', 'city_hall', 'public_bldg', 'government', 'civic'}
    return False


def _public_facility_label_is_plausible(label, facility_key):
    label = str(label or '').strip().lower()
    if not label:
        return False
    if facility_key == 'Fire':
        return any(token in label for token in ('fire station', 'fire department', 'fire hall', 'rescue station', 'fire rescue', 'station'))
    if facility_key == 'Police':
        return any(token in label for token in ('police', 'sheriff', 'public safety', 'law enforcement', 'precinct', 'marshal'))
    if facility_key == 'School':
        return any(token in label for token in ('school', 'academy', 'elementary', 'middle school', 'high school', 'campus'))
    if facility_key == 'Library':
        return 'library' in label
    if facility_key == 'Government':
        return any(token in label for token in ('city hall', 'town hall', 'public works', 'municipal', 'government', 'civic center', 'administration'))
    return False


@st.cache_data(show_spinner=False)
def _reverse_geocode_public_facility_meta(lat, lon):
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat={lat}&lon={lon}&zoom=18&addressdetails=1&namedetails=1"
        req = urllib.request.Request(url, headers={'User-Agent': 'BRINC_COS_Optimizer/1.0'})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _public_facility_candidate_is_plausible(candidate, facility_key):
    try:
        lat = float(candidate.get('lat'))
        lon = float(candidate.get('lon'))
    except Exception:
        return False

    reverse_meta = _reverse_geocode_public_facility_meta(lat, lon) or {}
    reverse_type = str(reverse_meta.get('type') or '').strip().lower()
    reverse_class = str(reverse_meta.get('class') or '').strip().lower()
    display_name = str(reverse_meta.get('display_name') or '').strip().lower()
    address_blob = ' '.join(
        str(value).strip().lower()
        for value in (reverse_meta.get('address') or {}).values()
        if value
    )
    combined = ' '.join([reverse_type, reverse_class, display_name, address_blob]).strip()

    if any(bad in combined for bad in ('golf course', 'golf_course', 'house', 'residential', 'apartment', 'apartments')):
        return False
    return True


def _public_facility_candidate_score(candidate, facility_type, preferred_city="", preferred_state=""):
    facility_key = _normalize_public_facility_type(facility_type)
    label = str(candidate.get('matched_address') or candidate.get('label') or '').strip().lower()
    feature_type = str(candidate.get('feature_type') or '').strip().lower()
    score = 100

    if facility_key == 'Police':
        if any(token in label for token in ('police', 'sheriff', 'public safety', 'law enforcement', 'precinct', 'marshal')):
            score += 200
        else:
            score -= 500
    elif facility_key == 'Fire':
        if any(token in label for token in ('fire station', 'fire department', 'fire hall', 'rescue')):
            score += 200
        else:
            score -= 500
    elif facility_key == 'School':
        if any(token in label for token in ('school', 'academy', 'elementary', 'middle school', 'high school')):
            score += 180
        else:
            score -= 500
    elif facility_key == 'Library':
        if 'library' in label:
            score += 200
        else:
            score -= 500
    elif facility_key == 'Government':
        if any(token in label for token in ('city hall', 'town hall', 'public works', 'municipal', 'government', 'civic center', 'administration')):
            score += 180
        else:
            score -= 500

    if _public_facility_type_is_plausible(feature_type, facility_key):
        score += 250
    else:
        score -= 600

    if preferred_state:
        _state = preferred_state.lower()
        _abbr_to_full = {v: k for k, v in US_STATES_ABBR.items()}
        _full = _abbr_to_full.get(preferred_state.upper(), '').lower()
        if f", {_state}" in label or label.endswith(f" {_state}") or (_full and _full in label):
            score += 35
        else:
            score -= 20
    if preferred_city:
        if preferred_city.lower() in label:
            score += 25
        else:
            score -= 10
    return score


@st.cache_data(show_spinner=False)
def search_public_facility_candidates(query_str, facility_type, limit=6, preferred_city="", preferred_state=""):
    query_str = str(query_str or '').strip()
    if not query_str:
        return []

    facility_key = _normalize_public_facility_type(facility_type)
    if not facility_key:
        return []

    limit = max(1, min(int(limit or 6), 10))
    preferred_city = str(preferred_city or '').strip()
    preferred_state = str(preferred_state or '').strip().upper()
    queries = _public_facility_query_variants(query_str, facility_key, preferred_city, preferred_state)
    if not queries:
        return []

    candidates = []
    seen = set()
    provider_trace = []
    address_search_hits = 0

    def _add_candidate(label, lat, lon, raw_match=''):
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except Exception:
            return None
        dedupe_key = (round(lat_f, 6), round(lon_f, 6), str(label).strip().lower())
        if dedupe_key in seen:
            return None
        seen.add(dedupe_key)
        candidate = {
            'label': str(label).strip() or str(raw_match).strip() or query_str,
            'matched_address': str(raw_match).strip() or str(label).strip() or query_str,
            'lat': lat_f,
            'lon': lon_f,
            'source': 'OSM',
            'feature_type': '',
            'feature_class': '',
            '_score': 0,
        }
        candidates.append(candidate)
        return candidate

    def _ingest_address_matches(matches, source_name, query_text):
        nonlocal address_search_hits
        kept = 0
        for _match in matches or []:
            _label = str(_match.get('matched_address') or _match.get('label') or '').strip()
            if not _public_facility_label_is_plausible(_label, facility_key):
                continue
            _candidate = _add_candidate(
                _label,
                _match.get('lat'),
                _match.get('lon'),
                raw_match=_label,
            )
            if _candidate is not None:
                _candidate['source'] = str(_match.get('source') or source_name or 'lookup')
                _candidate['feature_type'] = str(_match.get('feature_type') or '').strip().lower()
                _candidate['feature_class'] = str(_match.get('feature_class') or '').strip().lower()
                if not _public_facility_candidate_is_plausible(_candidate, facility_key):
                    candidates.pop()
                    continue
                kept += 1
        address_search_hits += kept
        provider_trace.append({
            'provider': source_name,
            'query': query_text,
            'used': True,
            'match_count': kept,
            'status': 'ok',
        })

    for _query in queries:
        try:
            addr_matches = search_address_candidates(
                _query,
                limit=limit,
                preferred_city=preferred_city,
                preferred_state=preferred_state,
            )
            _ingest_address_matches(addr_matches, 'validated_address_search', _query)
        except Exception:
            provider_trace.append({'provider': 'validated_address_search', 'query': _query, 'used': True, 'match_count': 0, 'status': 'error'})

    if not candidates:
        for _query in queries:
            try:
                _params = urllib.parse.urlencode({
                    'format': 'jsonv2',
                    'q': _query,
                    'limit': str(limit),
                    'countrycodes': 'us',
                    'addressdetails': '1',
                })
                _url = f"https://nominatim.openstreetmap.org/search?{_params}"
                _req = urllib.request.Request(_url, headers={'User-Agent': 'BRINC_COS_Optimizer/1.0'})
                with urllib.request.urlopen(_req, timeout=8) as _resp:
                    _data = json.loads(_resp.read().decode('utf-8'))
                _matches = _data[:limit]
                provider_trace.append({'provider': 'OSM_POI', 'query': _query, 'used': True, 'match_count': len(_matches), 'status': 'ok'})
                for _match in _matches:
                    _label = _match.get('display_name', _query)
                    _feature_type = str(_match.get('type') or '').strip().lower()
                    _feature_class = str(_match.get('class') or '').strip().lower()
                    if not (_public_facility_type_is_plausible(_feature_type, facility_key) or _public_facility_label_is_plausible(_label, facility_key)):
                        continue
                    _candidate = _add_candidate(_label, _match.get('lat'), _match.get('lon'), raw_match=_label)
                    if _candidate is not None:
                        _candidate['source'] = 'OSM'
                        _candidate['feature_type'] = _feature_type
                        _candidate['feature_class'] = _feature_class
                        if not _public_facility_candidate_is_plausible(_candidate, facility_key):
                            candidates.pop()
                            continue
            except Exception:
                provider_trace.append({'provider': 'OSM_POI', 'query': _query, 'used': True, 'match_count': 0, 'status': 'error'})

    for _candidate in candidates:
        _candidate['_score'] = _public_facility_candidate_score(_candidate, facility_key, preferred_city=preferred_city, preferred_state=preferred_state)

    candidates.sort(key=lambda item: (-item.get('_score', 0), item.get('matched_address', '')))

    try:
        st.session_state['_last_geocode_trace'] = {
            'input': query_str,
            'facility_type': facility_key,
            'preferred_city': preferred_city,
            'preferred_state': preferred_state,
            'queries': queries,
            'providers': provider_trace,
            'candidate_count': len(candidates),
            'top_candidate': candidates[0]['matched_address'] if candidates else '',
            'public_facility_lookup': True,
        }
    except Exception:
        pass

    return [{k: v for k, v in _candidate.items() if k != '_score'} for _candidate in candidates[:limit]]

@st.cache_data(show_spinner=False)
def forward_geocode(address_str, preferred_city='', preferred_state=''):
    _matches = search_address_candidates(
        address_str,
        limit=1,
        preferred_city=preferred_city or '',
        preferred_state=preferred_state or '',
    )
    if _matches:
        return float(_matches[0]['lat']), float(_matches[0]['lon'])
    return None, None


def geocode_intersection_fallback_rows(intersection_df: pd.DataFrame, *, max_workers: int = 8, log_fn=None) -> pd.DataFrame:
    """Geocode intersection rows with the existing forward geocoder.

    The returned frame keeps source_id alignment so it can be merged back into
    the Census result dataframe alongside normal street-address matches.
    """
    if intersection_df is None or intersection_df.empty:
        return pd.DataFrame(columns=['source_id', 'input_address', 'match_status', 'match_type', 'matched_address', 'lonlat', 'tiger_id', 'side', 'lat', 'lon'])

    work = intersection_df.copy().reset_index(drop=True)
    if 'intersection_query' not in work.columns:
        work['intersection_query'] = work.apply(
            lambda row: ', '.join(
                [v for v in [row.get('street', ''), row.get('city', ''), row.get('state', ''), row.get('zip', '')] if str(v or '').strip()]
            ),
            axis=1,
        )

    work['intersection_query'] = work['intersection_query'].fillna('').astype(str).str.strip()
    unique_queries = [q for q in dict.fromkeys(work['intersection_query'].tolist()) if q]
    if not unique_queries:
        return pd.DataFrame(columns=['source_id', 'input_address', 'match_status', 'match_type', 'matched_address', 'lonlat', 'tiger_id', 'side', 'lat', 'lon'])

    worker_count = max(1, min(int(max_workers or 1), len(unique_queries)))
    results = {}
    if log_fn is not None:
        log_fn(f"Geocoding {len(unique_queries):,} unique intersection query string(s) with {worker_count} worker(s).")

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_map = {executor.submit(forward_geocode, query): query for query in unique_queries}
        for future in cf.as_completed(future_map):
            query = future_map[future]
            try:
                lat, lon = future.result()
            except Exception:
                lat, lon = None, None
            results[query] = (lat, lon)

    work['lat'] = work['intersection_query'].map(lambda q: results.get(q, (None, None))[0])
    work['lon'] = work['intersection_query'].map(lambda q: results.get(q, (None, None))[1])
    work = work.dropna(subset=['lat', 'lon']).copy()
    if work.empty:
        return pd.DataFrame(columns=['source_id', 'input_address', 'match_status', 'match_type', 'matched_address', 'lonlat', 'tiger_id', 'side', 'lat', 'lon'])

    work['input_address'] = work['intersection_query']
    work['match_status'] = 'intersection_fallback'
    work['match_type'] = 'intersection'
    work['matched_address'] = work['intersection_query']
    work['lonlat'] = work.apply(lambda row: f"{float(row['lon']):.6f},{float(row['lat']):.6f}", axis=1)
    work['tiger_id'] = ''
    work['side'] = ''
    work['geocode_source'] = 'forward_geocode_intersection'
    work['geocode_provider'] = 'mixed'
    return work

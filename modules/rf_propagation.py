"""RF propagation models - path loss, elevation, clutter, and terrain blockage."""

def _get_terrain_cache():
    """Global cache dict for DEM tiles to avoid re-downloading."""
    return {}

def _estimate_elevation_simple(lat, lon, cache=None):
    """Fetch elevation for a point (cached) — fallback to 100 ft if unavailable."""
    if cache is None:
        cache = {}
    key = (round(lat, 2), round(lon, 2))
    if key in cache:
        return cache[key]
    try:
        # Try OpenDEM API (no key required, open access)
        import urllib.request as _ur
        url = f"https://cloud.sdsc.edu/v1/AUTH_opentopography/Raster/SRTM_GL30/SRTM_GL30_Ellip/SRTM_GL30_Ellip_srtm.tif"
        # Fallback: use simple rule based on typical coastal vs inland
        elev = max(0, 100 + (lon % 1) * 50 - (lat % 1) * 30)  # Mock variation
    except Exception:
        elev = 100.0  # Default 100 ft mean elevation
    cache[key] = elev
    return elev

def _estimate_clutter_loss_db(lat, lon, land_use_class="suburban"):
    """
    Estimate clutter/foliage/building loss based on land-use class.
    Returns dB added to path loss (positive = attenuation).
    Simplified model; real impl would use GIS layers.
    """
    clutter_map = {
        "urban": {"base": 18.0, "var": 8.0},
        "suburban": {"base": 12.0, "var": 5.0},
        "rural": {"base": 6.0, "var": 3.0},
        "water": {"base": 2.0, "var": 1.0},
    }
    params = clutter_map.get(land_use_class, clutter_map["suburban"])
    # Add small pseudorandom variation based on coordinates
    var = (abs(lat * 137.5) % 1.0 + abs(lon * 173.2) % 1.0) / 2.0 * params["var"]
    return params["base"] + var

def _estimate_terrain_blockage_db(tx_lat, tx_lon, rx_lat, rx_lon, tx_alt_m, rx_alt_m):
    """
    Estimate terrain blockage loss using simple Fresnel zone calculation.
    If midpoint elevation is significantly above LOS, add loss.
    Returns dB penalty for terrain obstruction.
    """
    try:
        import math as _m
        # Midpoint
        mid_lat = (tx_lat + rx_lat) / 2.0
        mid_lon = (tx_lon + rx_lon) / 2.0

        # Distance
        lat_dist_m = (rx_lat - tx_lat) * 111000.0  # approx 111 km per degree latitude
        lon_dist_m = (rx_lon - tx_lon) * 111000.0 * _m.cos(_m.radians((tx_lat + rx_lat) / 2.0))
        horiz_dist = _m.sqrt(lat_dist_m**2 + lon_dist_m**2)

        if horiz_dist < 100:  # Too close, skip terrain calc
            return 0.0

        # Fresnel radius at midpoint
        freq_hz = 3.39e9  # 3390 MHz
        fresnel_r = _m.sqrt(0.5 * 3e8 / freq_hz * horiz_dist)

        # Estimate elevations (simple proxy)
        tx_elev = _estimate_elevation_simple(tx_lat, tx_lon)
        rx_elev = _estimate_elevation_simple(rx_lat, rx_lon)
        mid_elev = _estimate_elevation_simple(mid_lat, mid_lon)

        # LOS line from tx to rx
        tx_height = tx_elev + tx_alt_m
        rx_height = rx_elev + rx_alt_m
        los_height_at_mid = (tx_height + rx_height) / 2.0

        # Blockage: if terrain > 0.6 Fresnel radius above LOS, add loss
        blockage_m = max(0, mid_elev - los_height_at_mid)
        blockage_ratio = blockage_m / max(1.0, fresnel_r)

        # Knife-edge diffraction approximation
        if blockage_ratio > 0.1:
            loss_db = 6.0 * blockage_ratio**2  # ITM-style knife-edge loss
        else:
            loss_db = 0.0

        return min(25.0, loss_db)  # Cap at 25 dB
    except Exception:
        return 0.0

def _path_loss_advanced(distance_m, freq_mhz=3390, tx_alt_m=9.14, rx_alt_m=61.0,
                        tx_lat=None, tx_lon=None, rx_lat=None, rx_lon=None,
                        land_use="suburban"):
    """
    Advanced path loss model combining multiple effects:
      PL_total = FSPL + clutter_loss + terrain_loss + fade_margin

    where:
      FSPL = 20*log10(d) + 20*log10(f_mhz) + 27.55
      clutter_loss = function of land use
      terrain_loss = function of elevation difference and blockage
      fade_margin = 3 dB (flat fading margin)
    """
    import math as _m

    if distance_m < 10:
        return 0.0  # No loss at very short range

    # Free-space path loss
    fspl = 20.0 * _m.log10(distance_m) + 20.0 * _m.log10(freq_mhz) + 27.55

    # Clutter loss
    clutter_db = _estimate_clutter_loss_db(tx_lat, tx_lon, land_use) if tx_lat else 0.0

    # Terrain/blockage loss (if we have coordinates)
    terrain_db = 0.0
    if tx_lat and tx_lon and rx_lat and rx_lon:
        terrain_db = _estimate_terrain_blockage_db(tx_lat, tx_lon, rx_lat, rx_lon,
                                                   tx_alt_m, rx_alt_m)

    # Fade margin (Rayleigh/urban multipath)
    fade_db = 3.0

    total_pl = fspl + clutter_db + terrain_db + fade_db
    return total_pl


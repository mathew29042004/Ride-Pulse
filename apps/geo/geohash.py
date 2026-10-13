"""Geohash encoding: nearby points share a prefix, so ``GROUP BY left(geohash, 6)`` buckets
trips into ~1.2 km × 0.6 km cells for demand heatmaps with a plain B-tree index."""

_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"
_DECODE = {c: i for i, c in enumerate(_BASE32)}


def encode(lat: float, lng: float, precision: int = 7) -> str:
    lat_range, lng_range = [-90.0, 90.0], [-180.0, 180.0]
    chars, bits, bit_count, even = [], 0, 0, True
    while len(chars) < precision:
        rng, value = (lng_range, lng) if even else (lat_range, lat)
        mid = (rng[0] + rng[1]) / 2
        if value >= mid:
            bits = (bits << 1) | 1
            rng[0] = mid
        else:
            bits <<= 1
            rng[1] = mid
        even = not even
        bit_count += 1
        if bit_count == 5:
            chars.append(_BASE32[bits])
            bits, bit_count = 0, 0
    return "".join(chars)


def decode(geohash: str) -> tuple[float, float, float, float]:
    """Returns (lat, lng, lat_error, lng_error) for the centre of the cell."""
    lat_range, lng_range = [-90.0, 90.0], [-180.0, 180.0]
    even = True
    for char in geohash:
        value = _DECODE[char]
        for shift in range(4, -1, -1):
            bit = (value >> shift) & 1
            rng = lng_range if even else lat_range
            mid = (rng[0] + rng[1]) / 2
            if bit:
                rng[0] = mid
            else:
                rng[1] = mid
            even = not even
    lat = (lat_range[0] + lat_range[1]) / 2
    lng = (lng_range[0] + lng_range[1]) / 2
    return lat, lng, (lat_range[1] - lat_range[0]) / 2, (lng_range[1] - lng_range[0]) / 2

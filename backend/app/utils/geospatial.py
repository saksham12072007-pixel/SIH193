"""Utilities for geospatial operations (buffer polygon generation, etc.)."""

from dataclasses import dataclass


@dataclass
class Point:
    latitude: float
    longitude: float


@dataclass
class Polygon:
    """Simplified polygon representation for local development."""

    wkt: str


def generate_buffer_polygon(latitude: float, longitude: float, buffer_radius_meters: float = 50) -> Polygon:
    """
    Generate a buffer polygon around a point.
    For MVP/local dev, returns a WKT string representation.
    In production with PostGIS, this would use ST_Buffer.
    
    Args:
        latitude: Plot center latitude
        longitude: Plot center longitude
        buffer_radius_meters: Default 50m for small plots per TRD §3.2
    
    Returns:
        Polygon with WKT representation
    """
    # Rough approximation: 1 degree ≈ 111km
    buffer_degrees = buffer_radius_meters / 111000.0
    
    wkt = (
        f"POLYGON(("
        f"{longitude - buffer_degrees} {latitude - buffer_degrees}, "
        f"{longitude + buffer_degrees} {latitude - buffer_degrees}, "
        f"{longitude + buffer_degrees} {latitude + buffer_degrees}, "
        f"{longitude - buffer_degrees} {latitude + buffer_degrees}, "
        f"{longitude - buffer_degrees} {latitude - buffer_degrees}"
        f"))"
    )
    return Polygon(wkt=wkt)


def validate_india_bounds(latitude: float, longitude: float) -> bool:
    """Check if coordinates are within India's bounding box (rough check)."""
    # India roughly: 8°N - 35°N, 68°E - 97°E
    return 8 <= latitude <= 35 and 68 <= longitude <= 97

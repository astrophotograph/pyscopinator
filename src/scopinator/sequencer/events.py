"""Astronomical events for wait conditions."""

from datetime import datetime
from enum import Enum
from typing import Optional

from astropy import units as u
from astropy.coordinates import EarthLocation, get_sun
from astropy.time import Time


class AstronomicalEvent(str, Enum):
    """Astronomical events that can be used as wait conditions."""

    ASTRONOMICAL_DAWN = "astronomical_dawn"
    NAUTICAL_DAWN = "nautical_dawn"
    CIVIL_DAWN = "civil_dawn"
    SUNRISE = "sunrise"
    SUNSET = "sunset"
    CIVIL_DUSK = "civil_dusk"
    NAUTICAL_DUSK = "nautical_dusk"
    ASTRONOMICAL_DUSK = "astronomical_dusk"


def calculate_event_time(
    event: AstronomicalEvent,
    location: EarthLocation,
    date: Optional[datetime] = None,
) -> datetime:
    """Calculate the time of an astronomical event.

    Args:
        event: The astronomical event
        location: Observer's location on Earth
        date: Date for which to calculate (defaults to today)

    Returns:
        datetime: Time when the event occurs

    Raises:
        ValueError: If the event doesn't occur on the given date
    """
    if date is None:
        date = datetime.utcnow()

    time = Time(date)

    # Define altitude thresholds for different events
    event_altitudes = {
        AstronomicalEvent.ASTRONOMICAL_DAWN: -18 * u.deg,
        AstronomicalEvent.NAUTICAL_DAWN: -12 * u.deg,
        AstronomicalEvent.CIVIL_DAWN: -6 * u.deg,
        AstronomicalEvent.SUNRISE: -0.833 * u.deg,  # Account for refraction and sun's radius
        AstronomicalEvent.SUNSET: -0.833 * u.deg,
        AstronomicalEvent.CIVIL_DUSK: -6 * u.deg,
        AstronomicalEvent.NAUTICAL_DUSK: -12 * u.deg,
        AstronomicalEvent.ASTRONOMICAL_DUSK: -18 * u.deg,
    }

    target_altitude = event_altitudes[event]

    # For dawn events, we need the time when the sun is rising
    # For dusk events, we need the time when the sun is setting
    is_dawn = event in [
        AstronomicalEvent.ASTRONOMICAL_DAWN,
        AstronomicalEvent.NAUTICAL_DAWN,
        AstronomicalEvent.CIVIL_DAWN,
        AstronomicalEvent.SUNRISE,
    ]

    # Search for the event time (simplified - in production use astropy's built-in functions)
    # This is a basic implementation - for production use astroplan library
    from astropy.coordinates import AltAz

    # Sample times throughout the day
    times = Time(date) + (range(0, 24 * 60, 5)) * u.minute
    sun_positions = get_sun(times)
    altaz_frame = AltAz(obstime=times, location=location)
    altitudes = sun_positions.transform_to(altaz_frame).alt

    # Find when altitude crosses the threshold
    for i in range(len(altitudes) - 1):
        current_alt = altitudes[i]
        next_alt = altitudes[i + 1]

        if is_dawn:
            # Dawn: altitude increasing through threshold
            if current_alt < target_altitude <= next_alt:
                return times[i].datetime
        else:
            # Dusk: altitude decreasing through threshold
            if current_alt > target_altitude >= next_alt:
                return times[i].datetime

    raise ValueError(f"Event {event} does not occur on {date.date()}")

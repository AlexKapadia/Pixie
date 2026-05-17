"""Thin httpx wrapper around the Open-Meteo daily forecast endpoint."""
from __future__ import annotations

from typing import Any

import httpx

API_URL = "https://api.open-meteo.com/v1/forecast"


async def fetch_forecast(lat: float, lng: float, days: int) -> dict[str, Any]:
    params = {
        "latitude": lat,
        "longitude": lng,
        "daily": ",".join([
            "temperature_2m_max",
            "temperature_2m_min",
            "temperature_2m_mean",
            "precipitation_sum",
            "weathercode",
            "windspeed_10m_max",
        ]),
        "current_weather": "true",
        "forecast_days": max(1, min(int(days), 16)),
        "timezone": "auto",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(API_URL, params=params)
        response.raise_for_status()
        return response.json()


WEATHER_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Light rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Light snow", 73: "Moderate snow", 75: "Heavy snow",
    77: "Snow grains",
    80: "Rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Severe thunderstorm with hail",
}


def describe(code: int) -> str:
    return WEATHER_CODES.get(int(code), f"Code {code}")

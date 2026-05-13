"""Weather widget — Nominatim geocode + Open-Meteo forecast.

Mirrors Vane's ``weatherWidget.ts``. Two-stage:

1. Inner param-extractor LLM call → extract ``location: str | NOT_PRESENT``.
2. Nominatim search → (lat, lon, display_name, timezone) → Open-Meteo
   forecast (current + 24h hourly + 7d daily).

Graceful degradation on any HTTP / parse error.

See PLAN_AMENDMENTS_R1.md §A8 and RECON_INITIAL.md §5.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Optional

try:
    import httpx
except ModuleNotFoundError:  # pragma: no cover
    httpx = None

from ..helpers.widgets_registry import WidgetOutput, build_failure_output

if TYPE_CHECKING:
    from ..helpers.types import ClassifierOutput  # noqa: F401

__all__ = ["WeatherWidget"]

_log = logging.getLogger(__name__)

_USER_AGENT = "A0_Fauxplexica/0.1.0 (https://github.com/neurocis/a0_fauxplexica)"
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_OPENMETEO_URL = "https://api.open-meteo.com/v1/forecast"
_DEFAULT_TIMEOUT = 15.0

_EXTRACTOR_SYSTEM_PROMPT = """You extract a location (city / region / country) from a user query.

Rules:
- Output ONLY the bare location string (e.g. "Paris", "Brooklyn, NY", "Mount Fuji").
- Strip prefixes like "weather in", "forecast for", etc.
- If the query mentions no location at all, output exactly: NOT_PRESENT
- If the user says "here" / "my city" / no specific place, output: NOT_PRESENT
Never explain. Output the location only."""

# WMO weather code → short description. Matches Open-Meteo's documented codes.
_WEATHER_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def _weather_desc(code: int | None) -> str:
    if code is None:
        return "Unknown"
    return _WEATHER_CODES.get(int(code), f"Code {code}")


class WeatherWidget:
    """Weather widget — id ``'weather'``."""

    type: str = "weather"

    def should_execute(self, classification: "ClassifierOutput") -> bool:
        return _routing_widget_flag(classification, "weather")

    async def execute(
        self,
        *,
        chat_history: list,
        follow_up: str,
        classification: "ClassifierOutput",
        llm: Any,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> Optional[WidgetOutput]:
        if httpx is None:
            _log.warning("weather: httpx is not installed; weather widget unavailable")
            return build_failure_output(self.type, "Weather widget dependency 'httpx' is not installed in the backend runtime.")
        # Stage 1: extract location.
        try:
            location = await _extract_location(follow_up, chat_history, llm)
        except Exception as exc:  # noqa: BLE001
            _log.exception("weather: extractor LLM call failed: %s", exc)
            return build_failure_output(self.type, f"extractor failed: {exc}")

        if not location or location.strip().upper() == "NOT_PRESENT":
            return WidgetOutput(
                type=self.type,
                llm_context="No location detected.",
                data={"error": "no_location"},
            )

        location = location.strip()

        # Stage 2: geocode + forecast. Use injected client for tests, or a fresh one.
        owns_client = http_client is None
        client = http_client or httpx.AsyncClient(
            timeout=_DEFAULT_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
        )
        try:
            geo = await _geocode(client, location)
            if geo is None:
                return WidgetOutput(
                    type=self.type,
                    llm_context=f"Could not locate '{location}'.",
                    data={"error": "geocode_empty", "location": location},
                )
            forecast = await _fetch_forecast(client, geo["lat"], geo["lon"])
        except httpx.HTTPError as exc:
            _log.warning("weather: HTTP error: %s", exc)
            return build_failure_output(self.type, f"HTTP error: {exc}")
        except Exception as exc:  # noqa: BLE001
            _log.exception("weather: unexpected error: %s", exc)
            return build_failure_output(self.type, str(exc))
        finally:
            if owns_client:
                await client.aclose()

        current = forecast.get("current") or {}
        hourly = forecast.get("hourly") or {}
        daily = forecast.get("daily") or {}
        timezone = forecast.get("timezone") or "UTC"

        # Slice hourly to next 24 entries — Open-Meteo returns 168h by default,
        # but with our params it'll start from "now" and we want the next day.
        hourly_24 = _slice_hourly(hourly, 24)
        daily_7 = _slice_daily(daily, 7)

        temp = current.get("temperature_2m")
        code = current.get("weather_code")
        desc = _weather_desc(code)

        llm_context = (
            f"Current weather in {geo['display_name']}: {temp}°C, {desc}. 7-day forecast available."
        )

        return WidgetOutput(
            type=self.type,
            llm_context=llm_context,
            data={
                "location": geo["display_name"],
                "query": location,
                "lat": geo["lat"],
                "lon": geo["lon"],
                "timezone": timezone,
                "current": current,
                "hourly_24h": hourly_24,
                "daily_7d": daily_7,
            },
        )


async def _geocode(client: httpx.AsyncClient, location: str) -> Optional[dict]:
    """Hit Nominatim and return the top match (or None)."""
    resp = await client.get(
        _NOMINATIM_URL,
        params={"q": location, "format": "json", "limit": 1},
        headers={"User-Agent": _USER_AGENT},
    )
    resp.raise_for_status()
    payload = resp.json()
    if not payload:
        return None
    top = payload[0]
    return {
        "display_name": top.get("display_name", location),
        "lat": float(top["lat"]),
        "lon": float(top["lon"]),
    }


async def _fetch_forecast(client: httpx.AsyncClient, lat: float, lon: float) -> dict:
    """Fetch the Open-Meteo forecast."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,weather_code,wind_speed_10m",
        "hourly": "temperature_2m,precipitation_probability,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
        "forecast_days": 7,
        "timezone": "auto",
    }
    resp = await client.get(_OPENMETEO_URL, params=params)
    resp.raise_for_status()
    return resp.json()


def _slice_hourly(hourly: dict, n: int) -> dict:
    """Return the first ``n`` entries of each parallel array in ``hourly``."""
    out: dict = {}
    for key, values in hourly.items():
        if isinstance(values, list):
            out[key] = values[:n]
        else:
            out[key] = values
    return out


def _slice_daily(daily: dict, n: int) -> dict:
    out: dict = {}
    for key, values in daily.items():
        if isinstance(values, list):
            out[key] = values[:n]
        else:
            out[key] = values
    return out


def _routing_widget_flag(classification: Any, key: str) -> bool:
    if classification is None:
        return False
    routing = getattr(classification, "routing", None)
    if routing is None and isinstance(classification, dict):
        routing = classification.get("routing")
    if routing is None:
        return False
    widgets = getattr(routing, "widgets", None)
    if widgets is None and isinstance(routing, dict):
        widgets = routing.get("widgets")
    if widgets is None:
        return False
    if isinstance(widgets, dict):
        return bool(widgets.get(key, False))
    return bool(getattr(widgets, key, False))


async def _extract_location(query: str, chat_history: list, llm: Any) -> str:
    history_snippet = _format_history(chat_history)
    user_msg = (
        f"{history_snippet}\nLatest user query: {query}\n\n"
        "Extract the location. Output the location string only, or NOT_PRESENT."
    )
    raw = await _invoke_llm(llm, system=_EXTRACTOR_SYSTEM_PROMPT, user=user_msg)
    return _strip_code_fence(raw)


def _format_history(chat_history: list, max_turns: int = 4) -> str:
    if not chat_history:
        return ""
    tail = chat_history[-max_turns:]
    lines = []
    for msg in tail:
        role = _get_attr(msg, "role", "user")
        content = _get_attr(msg, "content", "")
        if not content:
            continue
        lines.append(f"{role}: {content}")
    if not lines:
        return ""
    return "Recent context:\n" + "\n".join(lines)


def _get_attr(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


async def _invoke_llm(llm: Any, *, system: str, user: str) -> str:
    if hasattr(llm, "call_utility_model"):
        return await llm.call_utility_model(system=system, message=user)
    if callable(llm):
        try:
            return await llm(system=system, user=user)
        except TypeError:
            return await llm(f"{system}\n\n{user}")
    raise RuntimeError(f"unsupported llm handle: {type(llm).__name__}")


_FENCE_RE = re.compile(r"^```[a-zA-Z0-9]*\n?|\n?```$")


def _strip_code_fence(text: str) -> str:
    if not text:
        return ""
    t = text.strip()
    t = _FENCE_RE.sub("", t).strip()
    return t

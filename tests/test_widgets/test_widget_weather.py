"""Tests for ``tools/widget_weather.py`` (no network — httpx.MockTransport)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable

import httpx
import pytest

from a0_fauxplexica.tools.widget_weather import (
    WeatherWidget,
    _USER_AGENT,
    _weather_desc,
)


def _classification(weather: bool = True) -> SimpleNamespace:
    return SimpleNamespace(routing=SimpleNamespace(widgets={"weather": weather}))


def _stub_llm(response: str) -> Callable[..., Any]:
    async def _llm(*, system: str, user: str) -> str:  # noqa: ARG001
        return response
    return _llm


def _mock_transport(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _make_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=_mock_transport(handler),
        headers={"User-Agent": _USER_AGENT},
    )


def test_should_execute_routing_flag() -> None:
    w = WeatherWidget()
    assert w.should_execute(_classification(weather=True)) is True
    assert w.should_execute(_classification(weather=False)) is False


def test_weather_desc_lookup() -> None:
    assert _weather_desc(0) == "Clear sky"
    assert _weather_desc(95) == "Thunderstorm"
    assert _weather_desc(None) == "Unknown"
    assert _weather_desc(9999).startswith("Code ")


@pytest.mark.asyncio
async def test_happy_path_paris() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "nominatim" in request.url.host:
            assert request.url.params["q"] == "Paris"
            # Nominatim policy: require User-Agent.
            assert "A0_Fauxplexica" in request.headers["user-agent"]
            return httpx.Response(
                200,
                json=[
                    {
                        "display_name": "Paris, Île-de-France, France",
                        "lat": "48.8566",
                        "lon": "2.3522",
                    }
                ],
            )
        if "open-meteo" in request.url.host:
            return httpx.Response(
                200,
                json={
                    "timezone": "Europe/Paris",
                    "current": {"temperature_2m": 18.5, "weather_code": 2, "wind_speed_10m": 5.4},
                    "hourly": {
                        "time": [f"2026-05-11T{h:02d}:00" for h in range(48)],
                        "temperature_2m": list(range(48)),
                        "precipitation_probability": [0] * 48,
                        "weather_code": [2] * 48,
                    },
                    "daily": {
                        "time": [f"2026-05-{11 + d:02d}" for d in range(10)],
                        "temperature_2m_max": list(range(10)),
                        "temperature_2m_min": list(range(10)),
                        "precipitation_probability_max": [0] * 10,
                        "weather_code": [2] * 10,
                    },
                },
            )
        return httpx.Response(404)

    client = _make_client(handler)
    try:
        out = await WeatherWidget().execute(
            chat_history=[],
            follow_up="weather in Paris",
            classification=_classification(),
            llm=_stub_llm("Paris"),
            http_client=client,
        )
    finally:
        await client.aclose()

    assert out is not None
    assert out.type == "weather"
    assert out.data["location"] == "Paris, Île-de-France, France"
    assert out.data["lat"] == pytest.approx(48.8566)
    assert out.data["lon"] == pytest.approx(2.3522)
    assert out.data["timezone"] == "Europe/Paris"
    # Hourly sliced to 24.
    assert len(out.data["hourly_24h"]["temperature_2m"]) == 24
    # Daily sliced to 7.
    assert len(out.data["daily_7d"]["temperature_2m_max"]) == 7
    assert "Partly cloudy" in out.llm_context
    assert "18.5" in out.llm_context


@pytest.mark.asyncio
async def test_no_location_returns_no_location_output() -> None:
    client = _make_client(lambda r: httpx.Response(500))  # never hit
    try:
        out = await WeatherWidget().execute(
            chat_history=[],
            follow_up="what's the time",
            classification=_classification(),
            llm=_stub_llm("NOT_PRESENT"),
            http_client=client,
        )
    finally:
        await client.aclose()
    assert out is not None
    assert out.data["error"] == "no_location"
    assert out.llm_context == "No location detected."


@pytest.mark.asyncio
async def test_geocode_empty_returns_graceful() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "nominatim" in request.url.host:
            return httpx.Response(200, json=[])
        return httpx.Response(500)

    client = _make_client(handler)
    try:
        out = await WeatherWidget().execute(
            chat_history=[],
            follow_up="weather in Bogusville",
            classification=_classification(),
            llm=_stub_llm("Bogusville"),
            http_client=client,
        )
    finally:
        await client.aclose()
    assert out is not None
    assert out.data["error"] == "geocode_empty"
    assert "Bogusville" in out.llm_context


@pytest.mark.asyncio
async def test_open_meteo_500_returns_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "nominatim" in request.url.host:
            return httpx.Response(
                200,
                json=[{"display_name": "X", "lat": "0", "lon": "0"}],
            )
        return httpx.Response(500, json={"error": "forecast broke"})

    client = _make_client(handler)
    try:
        out = await WeatherWidget().execute(
            chat_history=[],
            follow_up="weather in X",
            classification=_classification(),
            llm=_stub_llm("X"),
            http_client=client,
        )
    finally:
        await client.aclose()
    assert out is not None
    assert out.llm_context == "Failed to fetch weather data."
    assert "error" in out.data


@pytest.mark.asyncio
async def test_extractor_exception_graceful() -> None:
    async def boom(**kwargs: Any) -> str:
        raise RuntimeError("util model exploded")

    out = await WeatherWidget().execute(
        chat_history=[],
        follow_up="weather?",
        classification=_classification(),
        llm=boom,
    )
    assert out is not None
    assert out.llm_context == "Failed to fetch weather data."
    assert "util model exploded" in out.data["error"]

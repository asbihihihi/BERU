import asyncio

import httpx

from backend.config import Settings
from backend.agent.tool_registry import ToolRegistry
from backend.tools import register_builtin_tools
from backend.tools.live_info import LiveInformationService


def test_weather_uses_default_location_and_returns_structured_data():
    service = LiveInformationService(Settings())

    async def fake_json(url, params=None):
        assert "forecast" in url
        assert params["latitude"] == -7.4242
        return {"current": {"temperature_2m": 27, "relative_humidity_2m": 80, "weather_code": 3, "wind_speed_10m": 10, "time": "2026-09-16T09:00"}, "daily": {"time": ["2026-09-16"], "weather_code": [3], "temperature_2m_min": [23], "temperature_2m_max": [29], "precipitation_probability_max": [40]}}

    service._get_json = fake_json
    result = asyncio.run(service.get_weather({}))
    assert result["location"] == "Purwokerto"
    assert result["condition"] == "Berawan"
    assert result["forecast"][0]["rain_probability_percent"] == 40


def test_sports_schedule_and_results_return_actual_api_shape():
    service = LiveInformationService(Settings())

    async def fake_json(url, params=None):
        if "searchteams" in url:
            return {"teams": [{"idTeam": "1234", "strTeam": "Real Madrid"}]}
        return {"events": [{"dateEvent": "2026-09-17", "strTime": "20:00:00", "strHomeTeam": "Real Madrid", "strAwayTeam": "Test FC", "intHomeScore": "2", "intAwayScore": "1", "strLeague": "La Liga", "strStatus": "Match Finished"}]}

    service._get_json = fake_json
    schedule = asyncio.run(service.get_sports_schedule({"team": "Real Madrid"}))
    results = asyncio.run(service.get_sports_results({"team": "Real Madrid"}))
    assert schedule["events"][0]["home_team"] == "Real Madrid"
    assert results["events"][0]["home_score"] == "2"


def test_news_time_and_service_failure_are_safe():
    service = LiveInformationService(Settings())

    async def fake_text(url, params=None):
        return "<rss><channel><item><title>Berita teknologi</title><link>https://example.com/news</link><pubDate>Wed, 16 Sep 2026</pubDate><source>Example</source><description>Ringkas</description></item></channel></rss>"

    service._get_text = fake_text
    news = asyncio.run(service.get_latest_news({"query": "teknologi", "limit": 9}))
    current_time = asyncio.run(service.get_current_time({}))
    assert news["articles"][0]["source"] == "Example"
    assert len(news["articles"]) == 1
    assert current_time["timezone"] == "Asia/Jakarta"

    async def failed_json(*_args, **_kwargs):
        raise httpx.ConnectError("offline")

    service._get_json = failed_json
    unavailable = asyncio.run(service.get_weather({"location": "Jakarta"}))
    assert unavailable == {"error": True, "message": "Weather service unavailable", "location": "Jakarta"}


def test_live_tools_are_registered_for_llm_selection():
    registry = ToolRegistry()
    register_builtin_tools(registry)
    names = {item["name"] for item in registry.list()}
    assert {"get_weather", "get_sports_schedule", "get_sports_results", "get_latest_news", "get_current_time", "web_search"} <= names

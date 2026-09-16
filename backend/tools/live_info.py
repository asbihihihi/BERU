"""Async, key-safe tools for current weather, sports, news, and local time."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from backend.config import Settings, get_settings

LOG = logging.getLogger("beru.live_info")
try:
    JAKARTA = ZoneInfo("Asia/Jakarta")
except ZoneInfoNotFoundError:
    # Windows Python installations may not include the IANA tz database.
    # Jakarta has no daylight-saving changes, so UTC+7 is an exact fallback.
    JAKARTA = timezone(timedelta(hours=7), name="Asia/Jakarta")
HTTP_TIMEOUT = httpx.Timeout(10.0, connect=4.0)

WMO_CONDITIONS = {
    0: "Cerah", 1: "Sebagian besar cerah", 2: "Berawan sebagian", 3: "Berawan",
    45: "Berkabut", 48: "Kabut beku", 51: "Gerimis ringan", 53: "Gerimis",
    55: "Gerimis lebat", 61: "Hujan ringan", 63: "Hujan", 65: "Hujan lebat",
    71: "Salju ringan", 73: "Salju", 75: "Salju lebat", 80: "Hujan lokal ringan",
    81: "Hujan lokal", 82: "Hujan lokal lebat", 95: "Badai petir",
    96: "Badai petir dengan hujan es", 99: "Badai petir dengan hujan es lebat",
}


class LiveInformationService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def _get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    async def _get_text(self, url: str, params: dict[str, Any] | None = None) -> str:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url, params=params, headers={"User-Agent": "BERU/1.0"})
            response.raise_for_status()
            return response.text

    async def get_weather(self, arguments: dict[str, Any]) -> dict[str, Any]:
        requested = str(arguments.get("location") or self.settings.default_location).strip()
        try:
            if requested.casefold() == self.settings.default_location.casefold():
                name, latitude, longitude = self.settings.default_location, self.settings.default_latitude, self.settings.default_longitude
            else:
                geocoding = await self._get_json(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    {"name": requested, "count": 1, "language": "id", "format": "json"},
                )
                result = (geocoding.get("results") or [None])[0]
                if not result:
                    return {"error": True, "message": "Lokasi tidak ditemukan.", "location": requested}
                name, latitude, longitude = result["name"], result["latitude"], result["longitude"]

            data = await self._get_json("https://api.open-meteo.com/v1/forecast", {
                "latitude": latitude, "longitude": longitude, "timezone": "auto", "forecast_days": 2,
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            })
            current, daily = data.get("current", {}), data.get("daily", {})
            forecast = [
                {"date": day, "condition": WMO_CONDITIONS.get(code, "Tidak diketahui"), "temperature_min_c": low,
                 "temperature_max_c": high, "rain_probability_percent": rain}
                for day, code, low, high, rain in zip(
                    daily.get("time", []), daily.get("weather_code", []), daily.get("temperature_2m_min", []),
                    daily.get("temperature_2m_max", []), daily.get("precipitation_probability_max", []),
                )
            ]
            return {"location": name, "temperature_c": current.get("temperature_2m"),
                    "condition": WMO_CONDITIONS.get(current.get("weather_code"), "Tidak diketahui"),
                    "humidity_percent": current.get("relative_humidity_2m"), "wind_kmh": current.get("wind_speed_10m"),
                    "observed_at": current.get("time"), "forecast": forecast}
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            LOG.warning("Weather request failed (%s).", type(exc).__name__)
            return {"error": True, "message": "Weather service unavailable", "location": requested}

    async def _team(self, team: str) -> dict[str, Any] | None:
        data = await self._get_json(f"{self.settings.sports_api_base_url}/{self.settings.sports_api_key}/searchteams.php", {"t": team})
        teams = data.get("teams") or []
        return teams[0] if teams else None

    @staticmethod
    def _event(event: dict[str, Any]) -> dict[str, Any]:
        return {"date": event.get("dateEvent"), "time": event.get("strTime") or event.get("strTimestamp"),
                "home_team": event.get("strHomeTeam"), "away_team": event.get("strAwayTeam"),
                "home_score": event.get("intHomeScore"), "away_score": event.get("intAwayScore"),
                "competition": event.get("strLeague"), "status": event.get("strStatus")}

    async def _sports(self, arguments: dict[str, Any], endpoint: str) -> dict[str, Any]:
        team = str(arguments.get("team") or "").strip()
        requested_date = str(arguments.get("date") or "").strip()
        try:
            if team:
                found = await self._team(team)
                if not found:
                    return {"team": team, "events": [], "error": False, "message": "Data tim tidak ditemukan."}
                data = await self._get_json(f"{self.settings.sports_api_base_url}/{self.settings.sports_api_key}/{endpoint}.php", {"id": found["idTeam"]})
                events = data.get("events") or []
                return {"team": found.get("strTeam", team), "events": [self._event(event) for event in events]}
            day = requested_date or datetime.now(JAKARTA).date().isoformat()
            data = await self._get_json(f"{self.settings.sports_api_base_url}/{self.settings.sports_api_key}/eventsday.php", {"d": day, "s": "Soccer"})
            return {"date": day, "events": [self._event(event) for event in (data.get("events") or [])][:10]}
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            LOG.warning("Sports request failed (%s).", type(exc).__name__)
            return {"error": True, "message": "Sports service unavailable", "team": team}

    async def get_sports_schedule(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._sports(arguments, "eventsnext")

    async def get_sports_results(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._sports(arguments, "eventslast")

    async def get_latest_news(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query") or "berita terbaru").strip()
        limit = max(1, min(int(arguments.get("limit", 5)), 5))
        try:
            xml = await self._get_text("https://news.google.com/rss/search", {"q": query, "hl": "id", "gl": "ID", "ceid": "ID:id"})
            root = ElementTree.fromstring(xml)
            articles = []
            for item in root.findall("./channel/item")[:limit]:
                source = item.find("source")
                link = (item.findtext("link") or "").strip()
                articles.append({"title": item.findtext("title") or "", "url": link,
                                 "source": source.text if source is not None else urlparse(link).netloc,
                                 "published_at": item.findtext("pubDate") or "", "summary": item.findtext("description") or ""})
            return {"query": query, "articles": articles}
        except (httpx.HTTPError, ElementTree.ParseError, ValueError) as exc:
            LOG.warning("News request failed (%s).", type(exc).__name__)
            return {"error": True, "message": "News service unavailable", "query": query, "articles": []}

    async def get_current_time(self, _: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(JAKARTA)
        tomorrow = now.date() + timedelta(days=1)
        return {"timezone": "Asia/Jakarta", "iso_datetime": now.isoformat(), "time": now.strftime("%H:%M"),
                "date": now.date().isoformat(), "day": ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")[now.weekday()],
                "tomorrow_date": tomorrow.isoformat(), "tomorrow_day": ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")[tomorrow.weekday()]}


service = LiveInformationService(get_settings())

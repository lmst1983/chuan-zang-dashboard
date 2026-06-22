#!/usr/bin/env python3
"""Refresh public weather and official bulletin metadata for the G318 dashboard."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "dashboard.json"
TZ = dt.timezone(dt.timedelta(hours=8))
USER_AGENT = "Mozilla/5.0 (compatible; G318PublicDashboard/1.0; public-data-aggregator)"

XIZANG_LIST_URL = "https://jtt.xizang.gov.cn/bsfw/cxfw/"
SICHUAN_ROAD_URL = "https://jtt.sc.gov.cn/jtt/c101919/speed_jk.shtml"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

ROUTE = [
    {"name": "成都", "lat": 30.5728, "lon": 104.0668, "note": "起点"},
    {"name": "雅安", "lat": 29.9805, "lon": 103.0133, "note": "雨城"},
    {"name": "康定", "lat": 30.0507, "lon": 101.9638, "note": "折多山前"},
    {"name": "新都桥", "lat": 30.0027, "lon": 101.4911, "note": "高原路段"},
    {"name": "雅江", "lat": 30.0315, "lon": 101.0144, "note": "剪子弯山"},
    {"name": "理塘", "lat": 29.9960, "lon": 100.2696, "note": "高海拔"},
    {"name": "巴塘", "lat": 30.0054, "lon": 99.1107, "note": "金沙江前"},
    {"name": "芒康", "lat": 29.6866, "lon": 98.5931, "note": "进藏首站"},
    {"name": "左贡", "lat": 29.6711, "lon": 97.8409, "note": "东达山"},
    {"name": "八宿", "lat": 30.0532, "lon": 96.9178, "note": "业拉山"},
    {"name": "波密", "lat": 29.8597, "lon": 95.7682, "note": "易受降雨影响"},
    {"name": "林芝", "lat": 29.6489, "lon": 94.3615, "note": "色季拉山"},
    {"name": "拉萨", "lat": 29.6520, "lon": 91.1721, "note": "终点"},
]

WEATHER_DESCRIPTIONS = {
    0: "晴朗",
    1: "大部晴朗",
    2: "局部多云",
    3: "阴天",
    45: "有雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "较强毛毛雨",
    56: "冻毛毛雨",
    57: "强冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "阵雨",
    81: "较强阵雨",
    82: "强阵雨",
    85: "阵雪",
    86: "强阵雪",
    95: "雷暴",
    96: "雷暴伴冰雹",
    99: "强雷暴伴冰雹",
}


def now_iso() -> str:
    return dt.datetime.now(TZ).replace(microsecond=0).isoformat()


def fetch_text(url: str, timeout: int = 25) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except urllib.error.URLError as error:
        # Some Chinese government sites intermittently close Python's TLS
        # handshake early. curl is a pragmatic fallback and is available on
        # both macOS and GitHub Actions runners.
        if "EOF occurred in violation of protocol" not in str(error):
            raise
        result = subprocess.run(
            [
                "curl",
                "--silent",
                "--show-error",
                "-L",
                "--max-time",
                str(timeout),
                "-A",
                USER_AGENT,
                url,
            ],
            check=True,
            capture_output=True,
        )
        return result.stdout.decode("utf-8", errors="replace")


def fetch_json(url: str, timeout: int = 25) -> Any:
    return json.loads(fetch_text(url, timeout=timeout))


def weather_risk(
    current_code: int,
    precipitation_probability: float,
    wind: float,
    precipitation_sum: float = 0,
) -> tuple[str, str]:
    if current_code >= 95:
        return "high", "存在雷暴信号"
    if current_code in {65, 67, 75, 82, 86} or precipitation_sum >= 20 or wind >= 50:
        return "high", "强降水或大风风险"
    if current_code >= 51 or precipitation_probability >= 60 or precipitation_sum >= 5 or wind >= 32:
        return "medium", "降水或风力需关注"
    return "low", "未见突出天气信号"


def fetch_weather() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params = {
        "latitude": ",".join(str(item["lat"]) for item in ROUTE),
        "longitude": ",".join(str(item["lon"]) for item in ROUTE),
        "current": "temperature_2m,precipitation,weather_code,wind_speed_10m",
        "daily": (
            "weather_code,temperature_2m_max,temperature_2m_min,"
            "precipitation_sum,precipitation_probability_max,wind_speed_10m_max"
        ),
        "timezone": "Asia/Shanghai",
        "forecast_days": "1",
    }
    url = f"{OPEN_METEO_URL}?{urllib.parse.urlencode(params)}"
    payload = fetch_json(url)
    if not isinstance(payload, list) or len(payload) != len(ROUTE):
        raise ValueError("Open-Meteo batch response count does not match route points")

    route_data = []
    for point, forecast in zip(ROUTE, payload):
        current = forecast.get("current", {})
        daily = forecast.get("daily", {})
        current_code = int(current.get("weather_code", -1))
        precip = float((daily.get("precipitation_probability_max") or [0])[0] or 0)
        precip_sum = float((daily.get("precipitation_sum") or [0])[0] or 0)
        wind = float((daily.get("wind_speed_10m_max") or [0])[0] or 0)
        risk, reason = weather_risk(current_code, precip, wind, precip_sum)
        route_data.append(
            {
                **point,
                "risk": risk,
                "risk_reason": reason,
                "current": {
                    "time": current.get("time"),
                    "temperature": current.get("temperature_2m"),
                    "precipitation": current.get("precipitation"),
                    "weather_code": current_code,
                    "wind_speed": current.get("wind_speed_10m"),
                    "description": WEATHER_DESCRIPTIONS.get(current_code, "天气变化"),
                },
                "daily": {
                    "weather_code": (daily.get("weather_code") or [None])[0],
                    "temperature_max": (daily.get("temperature_2m_max") or [None])[0],
                    "temperature_min": (daily.get("temperature_2m_min") or [None])[0],
                    "precipitation_sum": (daily.get("precipitation_sum") or [None])[0],
                    "precipitation_probability_max": precip,
                    "wind_speed_max": wind,
                },
            }
        )

    source = {
        "name": "Open-Meteo 沿线天气",
        "category": "weather",
        "status": "ok",
        "checked_at": now_iso(),
        "message": "13 个城镇坐标的当前天气与当日预测已更新",
        "url": "https://open-meteo.com/",
    }
    return route_data, source


def plain_text(value: str) -> str:
    value = html.unescape(re.sub(r"<[^>]+>", " ", value))
    return re.sub(r"\s+", " ", value).strip()


def parse_xizang_latest(list_html: str) -> tuple[str, str]:
    pattern = re.compile(
        r'<a[^>]+href="([^"]+)"[^>]*>\s*全区国省公路路网运行情况\s*</a>\s*<span>\s*(\d{4}-\d{2}-\d{2})',
        re.I | re.S,
    )
    match = pattern.search(list_html)
    if not match:
        raise ValueError("未在西藏交通运输厅列表中找到路网运行通告")
    return urllib.parse.urljoin(XIZANG_LIST_URL, match.group(1)), match.group(2)


def parse_meta_description(article_html: str) -> str:
    match = re.search(r'<meta\s+name="Description"\s+content="(.*?)"\s*/?>', article_html, re.I | re.S)
    if not match:
        raise ValueError("通告页面缺少 Description 元数据")
    return plain_text(match.group(1))


def extract_route_notices(description: str, article_url: str, published_date: str) -> list[dict[str, Any]]:
    route_places = ("芒康", "左贡", "八宿", "波密", "林芝", "拉萨", "邦达", "然乌", "通麦", "鲁朗")
    sentences = [part.strip() for part in re.split(r"(?<=[。；])", description) if part.strip()]
    relevant = [
        sentence
        for sentence in sentences
        if re.search(r"(?:G|国道)\s*318", sentence, re.I) and any(place in sentence for place in route_places)
    ]
    notices = []
    for sentence in relevant[:8]:
        level = "high" if any(word in sentence for word in ("无法通行", "全封闭", "交通中断", "解除时间待定")) else "medium"
        notices.append(
            {
                "source": "西藏自治区交通运输厅",
                "published_at": f"{published_date}T12:00:00+08:00",
                "title": "G318 川藏南线相关管制信息",
                "summary": sentence[:320],
                "level": level,
                "url": article_url,
            }
        )
    return notices


def fetch_xizang() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    list_html = fetch_text(XIZANG_LIST_URL)
    article_url, published_date = parse_xizang_latest(list_html)
    description = parse_meta_description(fetch_text(article_url))
    notices = extract_route_notices(description, article_url, published_date)
    published = dt.date.fromisoformat(published_date)
    age_days = (dt.datetime.now(TZ).date() - published).days
    stale = age_days > 3
    source = {
        "name": "西藏自治区交通运输厅",
        "category": "road",
        "status": "stale" if stale else "ok",
        "checked_at": now_iso(),
        "published_at": published_date,
        "message": (
            f"最新公开路网通告发布于 {published_date}，距今 {age_days} 天；不能代表今日实时路况"
            if stale
            else f"已读取 {published_date} 发布的最新路网运行通告"
        ),
        "url": article_url,
    }
    if not notices:
        notices.append(
            {
                "source": "西藏自治区交通运输厅",
                "published_at": f"{published_date}T12:00:00+08:00",
                "title": "最新通告未匹配到川藏南线沿途 G318 条目",
                "summary": "仅表示该篇公开通告中未提取到匹配内容，不等于沿线畅通；请用 12328 或当地 122 复核。",
                "level": "info",
                "url": article_url,
            }
        )
    return notices, source


def fetch_sichuan_source() -> dict[str, Any]:
    page = fetch_text(SICHUAN_ROAD_URL)
    generated_match = re.search(r"页面生成时间\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", page)
    generated = generated_match.group(1) if generated_match else "未知"
    return {
        "name": "四川省交通运输厅路况页",
        "category": "road",
        "status": "partial",
        "checked_at": now_iso(),
        "message": f"页面可访问（页面标注生成时间 {generated}），但实时接口限制外部 IP 自动读取",
        "url": SICHUAN_ROAD_URL,
    }


def fallback_route(previous: dict[str, Any] | None) -> list[dict[str, Any]]:
    if previous and previous.get("route"):
        return previous["route"]
    return [
        {
            **point,
            "risk": "unknown",
            "risk_reason": "天气数据暂不可用",
            "current": None,
            "daily": None,
        }
        for point in ROUTE
    ]


def error_source(name: str, category: str, url: str, error: Exception) -> dict[str, Any]:
    detail = re.sub(r"\s+", " ", str(error)).strip()[:180]
    return {
        "name": name,
        "category": category,
        "status": "error",
        "checked_at": now_iso(),
        "message": f"本次更新失败：{type(error).__name__}" + (f"（{detail}）" if detail else ""),
        "url": url,
    }


def update(output: Path) -> dict[str, Any]:
    previous = None
    if output.exists():
        try:
            previous = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = None

    sources: list[dict[str, Any]] = []
    notices: list[dict[str, Any]] = []

    try:
        route, weather_source = fetch_weather()
        sources.append(weather_source)
    except Exception as error:  # keep dashboard usable when a source fails
        route = fallback_route(previous)
        sources.append(error_source("Open-Meteo 沿线天气", "weather", "https://open-meteo.com/", error))

    try:
        xizang_notices, xizang_source = fetch_xizang()
        notices.extend(xizang_notices)
        sources.append(xizang_source)
    except Exception as error:
        sources.append(error_source("西藏自治区交通运输厅", "road", XIZANG_LIST_URL, error))

    try:
        sources.append(fetch_sichuan_source())
    except Exception as error:
        sources.append(error_source("四川省交通运输厅路况页", "road", SICHUAN_ROAD_URL, error))

    payload = {
        "schema_version": 1,
        "generated_at": now_iso(),
        "route": route,
        "notices": notices,
        "sources": sources,
        "disclaimer": "仅汇总公开信息，不构成道路畅通保证。",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    output.write_text(serialized + "\n", encoding="utf-8")
    output.with_suffix(".js").write_text(f"window.DASHBOARD_DATA = {serialized};\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DATA_PATH)
    args = parser.parse_args()
    payload = update(args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "route_points": len(payload["route"]),
                "notices": len(payload["notices"]),
                "sources": {item["name"]: item["status"] for item in payload["sources"]},
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

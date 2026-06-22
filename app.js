const DATA_URL = "data/dashboard.json";
const REFRESH_SECONDS = 300;

const state = {
  data: null,
  secondsLeft: REFRESH_SECONDS,
  filter: "all",
};

const $ = (selector) => document.querySelector(selector);

function formatDateTime(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function riskLabel(level) {
  return { low: "较低", medium: "注意", high: "较高", unknown: "待确认" }[level] || "待确认";
}

function sourceStateLabel(status) {
  return { ok: "正常", partial: "受限", stale: "过期", error: "失败" }[status] || "未知";
}

function weatherIcon(code) {
  if (code === 0) return "晴";
  if ([1, 2, 3].includes(code)) return "云";
  if ([45, 48].includes(code)) return "雾";
  if (code >= 95) return "雷";
  if (code >= 71 && code <= 77) return "雪";
  if (code >= 51 && code <= 82) return "雨";
  return "变";
}

function renderMetrics(data) {
  const highAndMedium = data.route.filter((item) => ["high", "medium"].includes(item.risk)).length;
  const healthy = data.sources.filter((item) => item.status === "ok").length;
  $("#riskCount").textContent = highAndMedium;
  $("#noticeCount").textContent = data.notices.length;
  $("#sourceCount").textContent = `${healthy}/${data.sources.length}`;
  $("#sourceSubline").textContent = data.sources.some((item) => item.status !== "ok") ? "存在受限或过期来源" : "全部来源正常";
}

function renderHero(data) {
  const high = data.route.filter((item) => item.risk === "high").length;
  const medium = data.route.filter((item) => item.risk === "medium").length;
  const staleOfficial = data.sources.some((item) => ["stale", "error", "partial"].includes(item.status) && item.category === "road");

  let verdict = "仍需逐段确认";
  let summary = `天气模型标记 ${high} 个较高风险节点、${medium} 个注意节点。`;
  if (high > 0) verdict = "不建议盲目赶路";
  if (staleOfficial) summary += " 部分官方路况源不够新或自动采集受限，必须电话复核。";
  else summary += " 官方公开源已读取，但突发管制仍可能尚未上网。";

  $("#heroVerdict").textContent = verdict;
  $("#heroSummary").textContent = summary;
  $("#generatedAt").textContent = formatDateTime(data.generated_at);
}

function renderRoute(data) {
  $("#routeTrack").innerHTML = data.route.map((item) => `
    <article class="route-node" title="${item.name}：${riskLabel(item.risk)}">
      <div class="route-pin ${item.risk}"></div>
      <strong>${item.name}</strong>
      <small>${item.current ? `${Math.round(item.current.temperature)}° · ${weatherIcon(item.current.weather_code)}` : "暂无天气"}</small>
    </article>
  `).join("");
}

function shouldShowWeather(item) {
  if (state.filter === "high") return item.risk === "high";
  if (state.filter === "medium") return ["high", "medium"].includes(item.risk);
  return true;
}

function renderWeather(data) {
  const items = data.route.filter(shouldShowWeather);
  const target = $("#weatherGrid");
  if (!items.length) {
    target.innerHTML = $("#emptyTemplate").innerHTML;
    return;
  }

  target.innerHTML = items.map((item) => {
    if (!item.current || !item.daily) {
      return `
        <article class="weather-card">
          <div class="weather-top">
            <div class="weather-place"><strong>${item.name}</strong><small>${item.note || "G318 节点"}</small></div>
            <span class="risk-badge unknown">待确认</span>
          </div>
          <div class="empty-state">天气数据暂不可用</div>
        </article>`;
    }
    return `
      <article class="weather-card">
        <div class="weather-top">
          <div class="weather-place">
            <strong>${item.name}</strong>
            <small>${item.note || "城镇坐标预测"}</small>
          </div>
          <span class="risk-badge ${item.risk}">${riskLabel(item.risk)}</span>
        </div>
        <div class="weather-main">
          <div class="weather-temp">${Math.round(item.current.temperature)}°</div>
          <div class="weather-condition">${weatherIcon(item.current.weather_code)} · ${item.current.description}<br>${item.risk_reason}</div>
        </div>
        <div class="weather-details">
          <span>降雨概率<b>${Math.round(item.daily.precipitation_probability_max)}%</b></span>
          <span>最大风速<b>${Math.round(item.daily.wind_speed_max)} km/h</b></span>
          <span>温度范围<b>${Math.round(item.daily.temperature_min)}°–${Math.round(item.daily.temperature_max)}°</b></span>
        </div>
      </article>`;
  }).join("");
}

function renderNotices(data) {
  const target = $("#noticeList");
  const officialRoadSources = data.sources.filter((item) => item.category === "road");
  const staleCount = officialRoadSources.filter((item) => item.status === "stale").length;
  const freshness = $("#noticeFreshness");
  freshness.textContent = staleCount ? `${staleCount} 个来源过期` : "已检查公开源";
  freshness.classList.toggle("stale", staleCount > 0);

  if (!data.notices.length) {
    target.innerHTML = `
      <div class="empty-state">
        未提取到川藏南线相关通告。<br>这不等于道路畅通，请电话确认。
      </div>`;
    return;
  }

  target.innerHTML = data.notices.map((notice) => `
    <article class="notice-card ${notice.level || "info"}">
      <div class="notice-meta">
        <span>${notice.source}</span>
        <time>${formatDateTime(notice.published_at)}</time>
      </div>
      <h3>${notice.title}</h3>
      <p>${notice.summary}</p>
      ${notice.url ? `<a href="${notice.url}" target="_blank" rel="noreferrer">查看官方原文 ↗</a>` : ""}
    </article>
  `).join("");
}

function renderSources(data) {
  $("#sourceList").innerHTML = data.sources.map((source) => `
    <div class="source-row">
      <i class="source-state ${source.status}"></i>
      <div>
        <strong>${source.name} · ${sourceStateLabel(source.status)}</strong>
        <small>${source.message}</small>
      </div>
      ${source.url ? `<a href="${source.url}" target="_blank" rel="noreferrer">原站 ↗</a>` : ""}
    </div>
  `).join("");
}

function render(data) {
  renderHero(data);
  renderMetrics(data);
  renderRoute(data);
  renderWeather(data);
  renderNotices(data);
  renderSources(data);
}

async function loadData({ manual = false } = {}) {
  const button = $("#refreshButton");
  button.classList.add("loading");
  if (manual) button.textContent = "刷新中…";
  try {
    const response = await fetch(`${DATA_URL}?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (!Array.isArray(data.route) || !Array.isArray(data.sources)) throw new Error("数据格式不完整");
    state.data = data;
    state.secondsLeft = REFRESH_SECONDS;
    render(data);
  } catch (error) {
    if (window.DASHBOARD_DATA && Array.isArray(window.DASHBOARD_DATA.route)) {
      state.data = window.DASHBOARD_DATA;
      state.secondsLeft = REFRESH_SECONDS;
      render(window.DASHBOARD_DATA);
    } else {
      $("#heroSummary").innerHTML = `<span class="error-banner">数据文件读取失败：${error.message}。请通过本地服务器或部署后的网址打开。</span>`;
    }
  } finally {
    button.classList.remove("loading");
    button.textContent = "刷新数据";
  }
}

function tick() {
  state.secondsLeft -= 1;
  if (state.secondsLeft <= 0) loadData();
  const minutes = String(Math.floor(state.secondsLeft / 60)).padStart(2, "0");
  const seconds = String(state.secondsLeft % 60).padStart(2, "0");
  $("#countdown").textContent = `${minutes}:${seconds}`;
}

$("#refreshButton").addEventListener("click", () => loadData({ manual: true }));
$("#riskFilter").addEventListener("change", (event) => {
  state.filter = event.target.value;
  if (state.data) renderWeather(state.data);
});

loadData();
setInterval(tick, 1000);

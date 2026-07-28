import { useEffect, useMemo, useState } from "react";
import type { AppState, Config, DriverInstallProgress, Health, Hero, LogEntry, RunStatus } from "../types";
import { Icon } from "../components/Icon";
import { Panel } from "../components/Panel";
import { collapseRepeatedLogs } from "../lib/logs";

type DashboardProps = {
  config: Config;
  heroes: Hero[];
  state: AppState;
  health: Health;
  logs: LogEntry[];
  history: number[];
  tariff: { province?: string; price?: number; source?: string };
  starting: boolean;
  driverInstall: DriverInstallProgress;
  onConfig: (update: Partial<Config> | ((current: Config) => Partial<Config>)) => void;
  onRun: (loop: boolean) => void;
  onPause: () => void;
  onResume: () => void;
  onStop: () => void;
  onOverlay: (enabled: boolean) => void;
  onTariff: () => void;
  onDriver: () => void;
  onReset: () => void;
};

export function DashboardPage({
  config,
  heroes,
  state,
  health,
  logs,
  history,
  tariff,
  starting,
  driverInstall,
  onConfig,
  onRun,
  onPause,
  onResume,
  onStop,
  onOverlay,
  onTariff,
  onDriver,
  onReset,
}: DashboardProps) {
  const [query, setQuery] = useState("");
  const [currentTime, setCurrentTime] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setCurrentTime(new Date()), 1_000);
    return () => window.clearInterval(timer);
  }, []);
  const selected = useMemo(() => new Set(config.selected_heroes), [config.selected_heroes]);
  const groups = useMemo(() => {
    const result = new Map<string, Hero[]>();
    const normalizedQuery = query.trim().toLowerCase();
    heroes
      .filter((hero) => hero.display_name.toLowerCase().includes(normalizedQuery))
      .forEach((hero) => {
        const items = result.get(hero.category) || [];
        items.push(hero);
        result.set(hero.category, items);
      });
    return [...result.entries()];
  }, [heroes, query]);
  const locked = ["scheduled", "starting", "running", "paused", "stopping"].includes(state.status);
  const tariffValue = Number(config.custom_tariff || 0);
  const displayedLogs = useMemo(() => collapseRepeatedLogs(logs), [logs]);
  const nowLocal = formatDateTimeLocal(currentTime);
  const scheduledStart = config.start_at;
  const scheduledEnd = config.end_at || addSeconds(scheduledStart, config.duration_seconds);
  const predicted = config.unlimited_mode
    ? state.average_power / 1000
    : state.average_power / 1000 * config.duration_seconds / 3600;
  const chartHistory = downsample(history, 600);
  const chartMax = Math.max(100, ...chartHistory);
  const chartEndTime = new Date();
  const chartStartTime = new Date(
    chartEndTime.getTime() - Math.max(0, history.length - 1) * 1000,
  );
  const points = chartHistory.length > 1
    ? chartHistory
      .map((value, index) => `${index / (chartHistory.length - 1) * 100},${100 - Math.min(95, value / chartMax * 90)}`)
      .join(" ")
    : "";

  const toggleHero = (name: string) => {
    onConfig((current) => {
      const isSelected = current.selected_heroes.includes(name);
      const names = current.selected_heroes.filter((item) => item !== name);
      if (!isSelected) names.push(name);
      return { selected_heroes: names, hero_ratios: equalRatios(names) };
    });
  };
  const setRatio = (name: string, value: number) => {
    onConfig((current) => ({
      hero_ratios: rebalanceRatios(current.selected_heroes, current.hero_ratios, name, value),
    }));
  };
  const setDuration = (minutes: number) => {
    const duration_seconds = Math.max(60, Math.min(7 * 24 * 3600, Math.round(minutes * 60)));
    onConfig((current) => {
      const start_at = current.schedule_mode === "scheduled"
        ? current.start_at || defaultScheduledStart(currentTime)
        : nowLocal;
      return {
        duration_seconds,
        start_at,
        end_at: addSeconds(start_at, duration_seconds),
      };
    });
  };
  const setStart = (start_at: string) => {
    onConfig((current) => ({
      start_at,
      end_at: addSeconds(start_at, current.duration_seconds),
    }));
  };
  const setEnd = (end_at: string) => {
    const start = Date.parse(config.start_at);
    const end = Date.parse(end_at);
    onConfig({
      end_at,
      ...(Number.isFinite(start) && end > start
        ? { duration_seconds: Math.round((end - start) / 1000) }
        : {}),
    });
  };

  return (
    <div className="dashboard">
      <section className="dashboard-summary">
        <SummaryMetric label="任务状态" value={statusLabel(state.status)} tone={state.status} />
        <SummaryMetric label="实时功率" value={`${state.power.toFixed(1)} W`} />
        <SummaryMetric label="累计能耗" value={`${state.energy.toFixed(4)} kWh`} />
        <SummaryMetric label="预计费用" value={`¥ ${(predicted * tariffValue).toFixed(3)}`} />
        <div className="flow-brief">
          <div>
            <small>{state.mode === "loop" ? "LOOP2 MODE" : "AUTOMATION FLOW"}</small>
            <b>{state.current_step || (state.status === "scheduled" ? `等待 ${formatDate(state.scheduled_for)}` : "等待任务启动")}</b>
          </div>
          <span>{state.next_step ? `下一步：${state.next_step}` : "请保持游戏窗口可见且无遮挡"}</span>
        </div>
      </section>

      <section className="dashboard-grid">
        <div className="dashboard-column roster-column">
          <Panel
            title="英雄编队"
            eyebrow={`HERO ROSTER · ${selected.size} SELECTED`}
            className="dashboard-hero-panel"
            action={(
              <label className="search">
                <span>⌕</span>
                <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索英雄" />
              </label>
            )}
          >
            <div className="hero-scroll">
              {groups.map(([category, items]) => (
                <div className="hero-group" key={category}>
                  <h3><span />{category}<small>{items.length}</small></h3>
                  <div className="hero-grid">
                    {items.map((hero) => (
                      <button
                        disabled={locked}
                        key={hero.name}
                        className={selected.has(hero.name) ? "hero-card selected" : "hero-card"}
                        onClick={() => toggleHero(hero.name)}
                      >
                        <img src={hero.image} alt={hero.display_name} loading="lazy" />
                        <b>{hero.display_name}</b>
                        <i>{selected.has(hero.name) ? "✓" : "+"}</i>
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </Panel>

          <Panel
            title="出场比例"
            eyebrow="SELECTION WEIGHT"
            className="dashboard-ratio-panel"
            action={(
              <button
                className="text-button"
                disabled={locked || selected.size < 2}
                onClick={() => onConfig((current) => ({ hero_ratios: equalRatios(current.selected_heroes) }))}
              >
                平均分配
              </button>
            )}
          >
            <div className="ratio-list">
              {config.selected_heroes.length
                ? config.selected_heroes.map((name) => (
                  <label className="ratio-row" key={name}>
                    <span>{name.trim()}</span>
                    <input
                      disabled={locked || selected.size < 2}
                      type="range"
                      min="0"
                      max="100"
                      value={config.hero_ratios[name] || 0}
                      onChange={(event) => setRatio(name, Number(event.target.value))}
                    />
                    <output>{config.hero_ratios[name] || 0}%</output>
                  </label>
                ))
                : <Empty text="至少选择一名英雄" />}
              {selected.size === 1 && (
                <p className="ratio-hint">当前唯一英雄固定为 100%，选择至少两名后可调整比例</p>
              )}
            </div>
          </Panel>
        </div>

        <div className="dashboard-column operation-column">
          <Panel title="运行计划" eyebrow="SCHEDULE" className="dashboard-schedule-panel">
            <div className="segmented">
              <button disabled={locked} className={config.schedule_mode === "immediate" ? "active" : ""} onClick={() => onConfig({ schedule_mode: "immediate" })}>立即运行</button>
              <button
                disabled={locked}
                className={config.schedule_mode === "scheduled" ? "active" : ""}
                onClick={() => {
                  const start_at = defaultScheduledStart(currentTime);
                  onConfig({
                    schedule_mode: "scheduled",
                    start_at,
                    end_at: addSeconds(start_at, config.duration_seconds),
                  });
                }}
              >
                预约启动
              </button>
            </div>
            <div className="form-grid">
              {config.schedule_mode === "scheduled" && (
                <label>
                  <span>开始时间</span>
                  <input
                    type="datetime-local"
                    step="1"
                    min={nowLocal}
                    value={scheduledStart}
                    disabled={locked}
                    onChange={(event) => setStart(event.target.value)}
                  />
                </label>
              )}
              {!config.unlimited_mode && (
                <label><span>运行时长（分钟）</span><input disabled={locked} type="number" min="1" max="10080" value={Math.round(config.duration_seconds / 60)} onChange={(event) => setDuration(Number(event.target.value))} /></label>
              )}
              {config.schedule_mode === "scheduled" && !config.unlimited_mode && (
                <label>
                  <span>结束时间</span>
                  <input
                    disabled={locked}
                    type="datetime-local"
                    step="1"
                    min={addSeconds(scheduledStart, 60)}
                    max={addSeconds(scheduledStart, 7 * 24 * 3600)}
                    value={scheduledEnd}
                    onChange={(event) => setEnd(event.target.value)}
                  />
                </label>
              )}
              <label>
                <span>鼠标移动速度</span>
                <div className="input-unit">
                  <input disabled={locked} type="number" min="100" max="2000" value={config.mouse_speed} onChange={(event) => onConfig({ mouse_speed: Number(event.target.value) })} />
                  <i>px/s</i>
                </div>
              </label>
            </div>
            <div className="schedule-options">
              <label className="switch-row">
                <input
                  disabled={locked}
                  type="checkbox"
                  checked={config.unlimited_mode}
                  onChange={(event) => onConfig((current) => ({
                    unlimited_mode: event.target.checked,
                    ...(event.target.checked ? { auto_shutdown: "none" as const } : {}),
                    ...(!event.target.checked && current.schedule_mode === "scheduled"
                      ? { end_at: addSeconds(current.start_at, current.duration_seconds) }
                      : {}),
                  }))}
                />
                <i />
                <span><b>无限运行</b><small>运行至手动停止或按 F8</small></span>
              </label>
              <label className="select-row">
                <span><b>结束后操作</b><small>危险操作会再次确认</small></span>
                <select disabled={locked || config.unlimited_mode} value={config.auto_shutdown} onChange={(event) => onConfig({ auto_shutdown: event.target.value as Config["auto_shutdown"] })}>
                  <option value="none">不执行任何操作</option>
                  <option value="stop_only">关闭游戏</option>
                  <option value="shutdown">关闭电脑</option>
                  <option value="both">关闭游戏并关闭电脑</option>
                </select>
              </label>
            </div>
          </Panel>

          <Panel title="功耗趋势" eyebrow="LAST 5 MINUTES" className="dashboard-chart-panel">
            <div className="chart-value">
              <b>{state.power.toFixed(1)}</b><span>W</span>
              <small>平均 {state.average_power.toFixed(1)} W</small>
            </div>
            <svg className="line-chart" viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="本次任务功耗趋势图">
              <defs>
                <linearGradient id="dashboard-area" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stopColor="#f0642d" stopOpacity=".4" />
                  <stop offset="1" stopColor="#f0642d" stopOpacity="0" />
                </linearGradient>
              </defs>
              {[20, 40, 60, 80].map((y) => <line key={y} x1="0" y1={y} x2="100" y2={y} />)}
              {points && (
                <>
                  <polygon points={`0,100 ${points} 100,100`} fill="url(#dashboard-area)" />
                  <polyline points={points} />
                </>
              )}
            </svg>
            <div className="chart-axis">
              <span>{formatClock(chartStartTime)}</span>
              <span>{formatClock(chartEndTime)}</span>
            </div>
          </Panel>

          <Panel title="运行日志" eyebrow={`${logs.length} EVENTS`} className="dashboard-logs-panel">
            <div className="log-table">
              {displayedLogs.length
                ? [...displayedLogs].reverse().map((entry, index) => (
                  <div key={`${entry.timestamp}-${index}`}>
                    <time>{new Date(entry.timestamp).toLocaleTimeString()}</time>
                    <b className={entry.level}>{entry.level}</b>
                    <span className="log-message">
                      <span>{entry.message}</span>
                      {entry.repeatCount >= 3 && (
                        <em className="log-repeat" title={`连续出现 ${entry.repeatCount} 次`}>
                          ×{entry.repeatCount}
                        </em>
                      )}
                    </span>
                  </div>
                ))
                : <div className="empty-log">等待后端事件…</div>}
            </div>
          </Panel>
        </div>

        <div className="dashboard-column system-column">
          <Panel title="运行环境" eyebrow="CAPABILITIES" className="dashboard-health-panel">
            <div className="health-list">
              <HealthRow label="Python Sidecar" detail="自动化核心服务" ok={health.backend} />
              <HealthRow label="Interception 驱动" detail={health.driver_loaded ? "驱动已加载" : health.driver_installed ? "已安装，重启后加载" : "尚未安装"} ok={health.driver_loaded} warning={health.driver_installed} />
              <HealthRow label="功耗监控" detail={health.power_monitor_degraded ? "估算模式" : "硬件传感器可用"} ok={health.power_monitor} warning={health.power_monitor_degraded} />
              <HealthRow label="F8 紧急停止" detail="全局热键" ok={health.f8_hotkey} />
              <HealthRow label="识别覆盖层" detail="透明置顶窗口" ok={health.overlay_available} />
            </div>
            <button
              className={`primary-action driver-action ${driverInstall.status}`}
              onClick={onDriver}
              disabled={driverInstall.active}
              aria-busy={driverInstall.active}
            >
              {driverInstall.status !== "idle" && (
                <i
                  className="driver-progress-fill"
                  style={{ width: `${driverInstall.progress}%` }}
                  aria-hidden="true"
                />
              )}
              <span className="driver-action-label">
                <Icon name="refresh" />
                {driverInstall.active
                  ? `${driverInstall.message} · ${Math.round(driverInstall.progress)}%`
                  : driverInstall.status === "error"
                    ? "安装失败，点击重试"
                    : driverInstall.status === "success"
                      ? driverInstall.message
                      : health.driver_loaded ? "重新检查驱动" : "检查 / 安装驱动"}
              </span>
            </button>
          </Panel>

          <Panel title="系统设置" eyebrow="PREFERENCES" className="dashboard-settings-panel">
            <label className="feature-toggle compact-feature-toggle">
              <div><b>显示识别覆盖层</b><small>在游戏窗口显示识别区域和流程步骤</small></div>
              <input type="checkbox" checked={config.overlay_enabled} onChange={(event) => onOverlay(event.target.checked)} />
              <i />
            </label>
            <div className="settings-divider" />
            <div className="form-grid tariff-form">
              <label>
                <span>居民电价档位</span>
                <select value={config.tariff_tier} onChange={(event) => onConfig({ tariff_tier: Number(event.target.value) })}>
                  <option value="1">第一档</option>
                  <option value="2">第二档</option>
                  <option value="3">第三档</option>
                </select>
              </label>
              <label>
                <span>自定义电价（元/kWh）</span>
                <input type="number" min=".01" step=".01" value={config.custom_tariff} onChange={(event) => onConfig({ custom_tariff: event.target.value })} />
              </label>
            </div>
            <div className="tariff-result">
              <span><small>定位结果</small><b>{tariff.province || "尚未获取"}</b></span>
              <span><small>参考电价</small><b>{tariff.price ? `¥ ${tariff.price}/kWh` : "—"}</b></span>
              <em>{tariff.source || "LOCAL"}</em>
            </div>
            <div className="settings-actions">
              <button className="secondary-action" onClick={onTariff}><Icon name="bolt" />获取本地电价</button>
              <button className="secondary-action danger-outline" onClick={onReset}>恢复默认配置</button>
            </div>
          </Panel>
        </div>
      </section>

      <section className="dashboard-control-dock">
        <div className="dashboard-hotkey">
          <kbd>F8</kbd>
          <span><b>紧急停止</b><small>随时终止自动化</small></span>
        </div>
        <div className={`dock-state ${state.status}`}><i /><span>{statusLabel(state.status)}</span></div>
        <div className="control-actions">
          {!state.running && state.status !== "scheduled" && (
            <button className="loop-button" disabled={!selected.size || starting} onClick={() => onRun(true)}><Icon name="loop" />{starting ? "正在启动…" : "仅运行 Loop2"}</button>
          )}
          {state.status === "running" && <button onClick={onPause}><Icon name="pause" />暂停</button>}
          {state.status === "paused" && <button onClick={onResume}><Icon name="play" />恢复</button>}
          {(state.running || state.status === "scheduled") && <button className="stop-button" onClick={onStop}><Icon name="stop" />停止</button>}
          {!state.running && state.status !== "scheduled" && (
            <button className="launch-button" disabled={!selected.size || starting} onClick={() => onRun(false)}><Icon name="play" />{starting ? "正在启动…" : "启动任务"}</button>
          )}
        </div>
      </section>
    </div>
  );
}

function SummaryMetric({ label, value, tone }: { label: string; value: string; tone?: RunStatus }) {
  return (
    <div className={`summary-metric ${tone ? `status ${tone}` : ""}`}>
      <small>{label}</small>
      <b>{value}</b>
      {tone && <i />}
    </div>
  );
}

function HealthRow({ label, detail, ok, warning = false }: { label: string; detail: string; ok: boolean; warning?: boolean }) {
  return (
    <div>
      <i className={ok ? "ok" : warning ? "warning" : "error"}>{ok ? "✓" : warning ? "!" : "×"}</i>
      <span><b>{label}</b><small>{detail}</small></span>
      <em>{ok ? "READY" : warning ? "NOTICE" : "CHECK"}</em>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="empty-state"><b>—</b><span>{text}</span></div>;
}

function statusLabel(status: RunStatus): string {
  return {
    idle: "就绪",
    scheduled: "等待预约",
    starting: "正在初始化",
    running: "正在运行",
    paused: "已暂停",
    stopping: "正在停止",
    completed: "已完成",
    error: "发生错误",
  }[status];
}

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString() : "预约时间";
}

function formatClock(value: Date): string {
  return [value.getHours(), value.getMinutes(), value.getSeconds()]
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
}

function downsample(values: number[], maxPoints: number): number[] {
  if (values.length <= maxPoints) return values;
  const step = (values.length - 1) / (maxPoints - 1);
  return Array.from({ length: maxPoints }, (_, index) => values[Math.round(index * step)]);
}

function addSeconds(value: string, seconds: number): string {
  const date = new Date(value);
  if (!value || Number.isNaN(date.getTime())) return "";
  const result = new Date(date.getTime() + seconds * 1000);
  return formatDateTimeLocal(result);
}

function formatDateTimeLocal(value: Date): string {
  if (Number.isNaN(value.getTime())) return "";
  const offset = value.getTimezoneOffset() * 60_000;
  return new Date(value.getTime() - offset).toISOString().slice(0, 19);
}

function defaultScheduledStart(now: Date): string {
  const result = new Date(now.getTime() + 5 * 60_000);
  result.setSeconds(0, 0);
  return formatDateTimeLocal(result);
}

function equalRatios(names: string[]): Record<string, number> {
  if (!names.length) return {};
  const base = Math.floor(100 / names.length);
  const remainder = 100 - base * names.length;
  return Object.fromEntries(names.map((name, index) => [name, base + (index < remainder ? 1 : 0)]));
}

function rebalanceRatios(
  names: string[],
  ratios: Record<string, number>,
  current: string,
  value: number,
): Record<string, number> {
  if (names.length <= 1) return names.length ? { [names[0]]: 100 } : {};
  const fixed = Math.max(0, Math.min(100, value));
  const others = names.filter((name) => name !== current);
  const total = others.reduce((sum, name) => sum + (ratios[name] || 0), 0);
  const remaining = 100 - fixed;
  const result: Record<string, number> = { [current]: fixed };
  others.forEach((name) => {
    result[name] = total
      ? Math.floor((ratios[name] || 0) * remaining / total)
      : Math.floor(remaining / others.length);
  });
  let rest = 100 - Object.values(result).reduce((sum, number) => sum + number, 0);
  for (const name of others) {
    if (rest-- <= 0) break;
    result[name] += 1;
  }
  return result;
}

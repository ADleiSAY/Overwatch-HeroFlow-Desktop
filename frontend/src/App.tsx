import { useEffect, useRef, useState } from "react";
import { TitleBar } from "./components/TitleBar";
import { ConfirmDialog } from "./components/ConfirmDialog";
import { DashboardPage } from "./pages/DashboardPage";
import { backendStatus, connectBackend, rpc, subscribeBackend } from "./lib/rpc";
import { buildRunOptions } from "./lib/schedule";
import type { AppState, Bootstrap, Config, DriverInstallProgress, Health, LogEntry } from "./types";

const EMPTY_STATE: AppState = {
  status: "idle", running: false, paused: false, mode: "flow", current_step: "", next_step: "",
  scheduled_for: null, started_at: null, power: 0, energy: 0, average_power: 0,
  degraded_power: true, overlay_enabled: false, hotkey_registered: false, error: null,
};
const EMPTY_HEALTH: Health = {
  backend: false, mode: "bundled", power_monitor: false, power_monitor_degraded: true,
  f8_hotkey: false, overlay_available: false, driver_installed: false, driver_loaded: false,
};
const IDLE_DRIVER_INSTALL: DriverInstallProgress = {
  active: false, progress: 0, phase: "idle", message: "", status: "idle",
};

export function App() {
  const [online, setOnline] = useState(false);
  const [config, setConfig] = useState<Config | null>(null);
  const [heroes, setHeroes] = useState<Bootstrap["heroes"]>([]);
  const [state, setState] = useState<AppState>(EMPTY_STATE);
  const [health, setHealth] = useState<Health>(EMPTY_HEALTH);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [history, setHistory] = useState<number[]>([]);
  const [notice, setNotice] = useState("");
  const [tariff, setTariff] = useState<Record<string, any>>({});
  const [pendingLoop, setPendingLoop] = useState<boolean | null>(null);
  const [starting, setStarting] = useState(false);
  const [driverInstall, setDriverInstall] = useState<DriverInstallProgress>(IDLE_DRIVER_INSTALL);
  const [startupProgress, setStartupProgress] = useState(4);
  const [startupMessage, setStartupMessage] = useState("正在启动本地自动化服务");
  const saveTimer = useRef<number | undefined>(undefined);
  const saveRevision = useRef(0);
  const configRef = useRef<Config | null>(null);

  useEffect(() => {
    let poll = 0;
    let cancelled = false;
    let unsubscribe: () => void = () => undefined;
    const waitForBackend = async () => {
      await connectBackend();
      unsubscribe = subscribeBackend((message) => {
        if (message.type !== "event") return;
        if (message.event === "startup_progress") {
          setStartupProgress(Number(message.payload?.progress || 0));
          setStartupMessage(message.payload?.message || "正在启动 HeroFlow Core");
        }
        if (message.event === "state_snapshot") {
          setState(message.payload);
          setHealth((current) => ({ ...current, f8_hotkey: Boolean(message.payload?.hotkey_registered) }));
        }
        if (message.event === "flow_state") setState((current) => ({ ...current, ...message.payload }));
        if (message.event === "log_entry") setLogs((items) => [...items, message.payload].slice(-300));
        if (message.event === "backend_error") setNotice(message.payload?.message || "自动化服务发生错误");
        if (message.event === "emergency_stop") setNotice("F8 紧急停止已触发");
        if (message.event === "driver_install_progress") {
          setDriverInstall({
            active: true,
            progress: clampProgress(message.payload?.progress),
            phase: String(message.payload?.phase || "installing"),
            message: String(message.payload?.message || "正在安装驱动"),
            status: "working",
          });
        }
        if (message.event === "driver_install_finished") {
          const ok = Boolean(message.payload?.ok);
          const messageText = String(message.payload?.message || (ok ? "驱动安装完成" : "驱动安装失败"));
          setDriverInstall({
            active: false,
            progress: 100,
            phase: ok ? "complete" : "error",
            message: messageText,
            status: ok ? "success" : "error",
          });
          setNotice(messageText);
        }
      });
      for (let attempt = 0; attempt < 240 && !cancelled; attempt += 1) {
        const status = await backendStatus();
        setStartupProgress(Math.max(4, Math.min(96, Number(status.progress || 0))));
        setStartupMessage(status.message || "正在等待 HeroFlow Core");
        if (status.error) throw new Error(status.error);
        if (status.power_request_warning) setNotice(status.power_request_warning);
        if (status.available && status.ready) return;
        await new Promise((resolve) => window.setTimeout(resolve, 250));
      }
      throw new Error("HeroFlow Core 启动超时，请查看 backend-startup.log");
    };
    waitForBackend().then(() => {
      setStartupProgress(94);
      setStartupMessage("正在读取配置、英雄与驱动状态");
      return rpc<Bootstrap>("get_bootstrap", {}, 60_000);
    }).then((data) => {
      if (cancelled) return;
      setStartupProgress(100);
      configRef.current = data.config;
      setConfig(data.config); setHeroes(data.heroes); setState(data.state); setHealth(data.health); setHistory([data.state.power]); setOnline(true);
      poll = window.setInterval(() => rpc<AppState>("get_app_state").then((snapshot) => {
        setState(snapshot);
        setHealth((current) => ({ ...current, f8_hotkey: snapshot.hotkey_registered }));
        setOnline(true);
        setHistory((items) => [...items, snapshot.power].slice(-300));
      }).catch(() => setOnline(false)), 1000);
    }).catch((error) => {
      if (!cancelled) {
        setStartupMessage(error.message);
        setNotice(error.message);
      }
    });
    return () => { cancelled = true; unsubscribe(); window.clearInterval(poll); window.clearTimeout(saveTimer.current); };
  }, []);

  const updateConfig = (update: Partial<Config> | ((current: Config) => Partial<Config>)) => {
    const current = configRef.current;
    if (!current) return;
    const patch = typeof update === "function" ? update(current) : update;
    const next = { ...current, ...patch };
    const revision = ++saveRevision.current;
    configRef.current = next;
    setConfig(next);
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      rpc<Config>("save_config", { config: next }).then((saved) => {
        if (saveRevision.current !== revision) return;
        configRef.current = saved;
        setConfig(saved);
      }).catch((error) => {
        if (saveRevision.current === revision) setNotice(formatBackendError(error));
      });
    }, 350);
  };

  const start = async (loop: boolean, confirmationToken?: string) => {
    const currentConfig = configRef.current;
    if (!currentConfig) return;
    setStarting(true);
    setNotice(loop ? "正在启动 Loop2…" : "正在启动任务…");
    try {
      const revision = ++saveRevision.current;
      window.clearTimeout(saveTimer.current);
      const savedConfig = await rpc<Config>("save_config", { config: currentConfig });
      if (saveRevision.current === revision) {
        configRef.current = savedConfig;
        setConfig(savedConfig);
      }
      const options = buildRunOptions(savedConfig, loop, confirmationToken);
      const snapshot = await rpc<AppState>(loop ? "start_loop" : "start_flow", options);
      setState(snapshot); setPendingLoop(null); setNotice("");
    } catch (error: any) {
      setNotice(formatBackendError(error));
      setPendingLoop(null);
    } finally {
      setStarting(false);
    }
  };
  const requestStart = (loop: boolean) => {
    const currentConfig = configRef.current;
    if (!currentConfig || starting) return;
    if (!loop && currentConfig.auto_shutdown !== "none") setPendingLoop(loop);
    else void start(loop);
  };
  const confirmStart = async () => {
    const currentConfig = configRef.current;
    if (!currentConfig || pendingLoop === null) return;
    try {
      const result = await rpc<{ token: string }>("confirm_dangerous_action", { policy: currentConfig.auto_shutdown });
      await start(pendingLoop, result.token);
    } catch (error: any) { setNotice(formatBackendError(error)); setPendingLoop(null); }
  };
  const control = (method: string) => rpc<AppState>(method).then(setState).catch((error) => setNotice(error.message));
  const refreshHealth = () => rpc<Health>("get_health").then(setHealth).catch((error) => setNotice(error.message));
  const checkOrInstallDriver = async () => {
    if (driverInstall.active) return;
    setNotice("");
    setDriverInstall({
      active: true,
      progress: 3,
      phase: "checking",
      message: "正在检查 Interception 驱动",
      status: "working",
    });
    try {
      const current = await rpc<Health>("get_health");
      setHealth(current);
      if (current.driver_loaded) {
        setDriverInstall({
          active: false,
          progress: 100,
          phase: "complete",
          message: "Interception 驱动已加载",
          status: "success",
        });
        return;
      }
      if (current.driver_installed) {
        const restartMessage = "驱动已安装，请重启电脑后再检查";
        setDriverInstall({
          active: false,
          progress: 100,
          phase: "restart_required",
          message: restartMessage,
          status: "success",
        });
        setNotice(restartMessage);
        return;
      }
      setDriverInstall({
        active: true,
        progress: 8,
        phase: "preparing",
        message: "正在准备驱动安装",
        status: "working",
      });
      const result = await rpc<{ ok: boolean; message: string; requires_restart: boolean }>(
        "install_driver",
        {},
        360_000,
      );
      if (!result.ok) throw new Error(result.message || "驱动安装失败");
      await refreshHealth();
      setDriverInstall({
        active: false,
        progress: 100,
        phase: "complete",
        message: result.requires_restart ? "安装完成，请重启电脑" : "驱动已可用",
        status: "success",
      });
      setNotice(result.message || "驱动安装完成");
    } catch (error: any) {
      const message = formatBackendError(error);
      setDriverInstall((current) => ({
        ...current,
        active: false,
        phase: "error",
        message,
        status: "error",
      }));
      setNotice(message);
    }
  };

  if (!config) return (
    <div className="app-shell">
      <TitleBar online={false} />
      <div className="loading-screen">
        <div className="loader-mark">HF</div>
        <b>正在连接 HeroFlow Core</b>
        <span>{startupMessage}</span>
        <div className="startup-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={startupProgress}>
          <i style={{ width: `${startupProgress}%` }} />
        </div>
        <small>{Math.round(startupProgress)}%</small>
        {notice && <div className="startup-error">{notice}</div>}
      </div>
    </div>
  );
  return (
    <div className="app-shell">
      <TitleBar online={online} />
      <main className="dashboard-content">
        {notice && <div className="notice"><span>!</span><b>{notice}</b><button onClick={() => setNotice("")}>×</button></div>}
        <DashboardPage
          config={config}
          heroes={heroes}
          state={state}
          health={health}
          logs={logs}
          history={history}
          tariff={tariff}
          starting={starting}
          driverInstall={driverInstall}
          onConfig={updateConfig}
          onRun={requestStart}
          onPause={() => control("pause_flow")}
          onResume={() => control("resume_flow")}
          onStop={() => control("stop_flow")}
          onOverlay={(enabled) => rpc<{ enabled: boolean }>("toggle_overlay", { enabled })
            .then((value) => updateConfig({ overlay_enabled: value.enabled }))
            .catch((error) => setNotice(error.message))}
          onTariff={() => rpc<Record<string, any>>("refresh_tariff", { tier: config.tariff_tier })
            .then(setTariff)
            .catch((error) => setNotice(error.message))}
          onDriver={() => void checkOrInstallDriver()}
          onReset={() => {
            const revision = ++saveRevision.current;
            window.clearTimeout(saveTimer.current);
            rpc<Config>("reset_config").then((saved) => {
              if (saveRevision.current !== revision) return;
              configRef.current = saved;
              setConfig(saved);
            }).catch((error) => setNotice(formatBackendError(error)));
          }}
        />
      </main>
      {pendingLoop !== null && <ConfirmDialog title="确认结束后操作" onCancel={() => setPendingLoop(null)} onConfirm={confirmStart}><p>本次任务结束后将执行“{shutdownLabel(config.auto_shutdown)}”。关闭电脑前会显示倒计时，可通过界面或 <kbd>F8</kbd> 取消。</p></ConfirmDialog>}
    </div>
  );
}

function clampProgress(value: unknown): number {
  const progress = Number(value);
  return Number.isFinite(progress) ? Math.max(0, Math.min(100, progress)) : 0;
}

function shutdownLabel(value: Config["auto_shutdown"]) {
  return { none: "不执行操作", stop_only: "关闭游戏", shutdown: "关闭电脑", both: "关闭游戏并关闭电脑" }[value];
}

function formatBackendError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  if (message.includes("overwatch_window_unavailable")) {
    return "未检测到《守望先锋》游戏窗口，请先启动游戏并保持窗口可见";
  }
  if (message.includes("screen_capture_unavailable")) {
    return "无法读取《守望先锋》画面，请确认游戏窗口可见且没有最小化";
  }
  if (message.includes("at_least_one_hero_required")) {
    return "请至少选择一名英雄后再启动任务";
  }
  if (message.includes("scheduled_start_required")) {
    return "请先选择预约启动时间，或切换为“立即运行”";
  }
  if (message.includes("invalid_scheduled_start")) {
    return "预约启动时间格式无效，请重新选择";
  }
  if (message.includes("scheduled_start_must_be_future")) {
    return "预约启动时间必须晚于当前时间";
  }
  if (message.includes("invalid_scheduled_end")) {
    return "预约结束时间格式无效，请重新选择";
  }
  if (message.includes("scheduled_end_must_be_after_start")) {
    return "预约结束时间必须晚于开始时间";
  }
  if (message.includes("invalid_duration")) {
    return "运行时长必须在 1 分钟到 7 天之间";
  }
  if (message.includes("invalid_schedule_mode")) {
    return "运行计划类型无效，请重新选择";
  }
  return message;
}

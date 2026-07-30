import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { AppState, Bootstrap, Config, Health, Hero, RpcMessage } from "../types";

let requestId = 0;
let unlisten: UnlistenFn | undefined;
const pending = new Map<number, {
  resolve: (value: any) => void;
  reject: (error: Error) => void;
  timer: number;
}>();
const subscribers = new Set<(message: RpcMessage) => void>();
export const isTauriRuntime = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

export type BackendStatus = {
  available: boolean;
  ready?: boolean;
  phase?: string;
  message?: string;
  progress?: number;
  error?: string;
  system_awake?: boolean;
  power_request_warning?: string;
};

export async function backendStatus(): Promise<BackendStatus> {
  return isTauriRuntime
    ? invoke("backend_status")
    : {
      available: true,
      ready: true,
      phase: "ready",
      message: "浏览器预览已就绪",
      progress: 100,
      system_awake: true,
    };
}

export async function connectBackend(): Promise<() => void> {
  if (!isTauriRuntime) return () => undefined;
  if (!unlisten) {
    unlisten = await listen<RpcMessage>("backend-message", ({ payload }) => {
      if (payload.type === "response" && payload.id !== undefined) {
        const item = pending.get(payload.id);
        if (item) {
          window.clearTimeout(item.timer);
          pending.delete(payload.id);
          payload.ok
            ? item.resolve(payload.result)
            : item.reject(new Error(payload.error?.message || "后端请求失败"));
        }
      }
      subscribers.forEach((subscriber) => subscriber(payload));
    });
  }
  return () => undefined;
}

export function subscribeBackend(subscriber: (message: RpcMessage) => void): () => void {
  subscribers.add(subscriber);
  return () => subscribers.delete(subscriber);
}

export function rpc<T>(method: string, params: Record<string, unknown> = {}, timeoutMs = 15_000): Promise<T> {
  if (!isTauriRuntime) return mockRpc<T>(method, params);
  const id = ++requestId;
  const request = stringifyAscii({ id, version: 2, method, params });
  return new Promise<T>((resolve, reject) => {
    const timer = window.setTimeout(() => {
      pending.delete(id);
      reject(new Error("后端响应超时"));
    }, timeoutMs);
    pending.set(id, { resolve, reject, timer });
    invoke("backend_request", {
      request,
    }).catch((error) => {
      window.clearTimeout(timer);
      pending.delete(id);
      reject(new Error(String(error)));
    });
  });
}

export function stringifyAscii(value: unknown): string {
  return JSON.stringify(value).replace(
    /[\u007f-\uffff]/g,
    (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`,
  );
}

export function disconnectBackend(reason = "后端已断开"): void {
  pending.forEach(({ reject, timer }) => {
    window.clearTimeout(timer);
    reject(new Error(reason));
  });
  pending.clear();
}

const MOCK_HEROES: Hero[] = [
  ["D.Va", "坦克"], ["莱因哈特", "坦克"], ["温斯顿", "坦克"], ["查莉娅", "坦克"],
  ["源氏", "输出"], ["猎空", "输出"], ["卡西迪", "输出"], ["半藏", "输出"],
  ["安娜", "辅助"], ["天使", "辅助"], ["雾子", "辅助"], ["卢西奥", "辅助"],
].map(([name, category]) => ({ name, display_name: name, category, image: `/heroes/${name}.png` }));

let mockConfig: Config = {
  schema_version: 2,
  overlay_enabled: false,
  mouse_speed: 500,
  auto_shutdown: "none",
  unlimited_mode: false,
  schedule_mode: "immediate",
  start_at: "",
  end_at: "",
  duration_seconds: 3600,
  selected_heroes: ["D.Va", "安娜"],
  hero_ratios: { "D.Va": 50, "安娜": 50 },
  tariff_tier: 1,
  custom_tariff: "0.52",
};
let mockState: AppState = {
  status: "idle",
  running: false,
  paused: false,
  mode: "flow",
  current_step: "",
  next_step: "",
  scheduled_for: null,
  started_at: null,
  power: 118.4,
  energy: 0.0281,
  average_power: 115.8,
  degraded_power: false,
  overlay_enabled: false,
  hotkey_registered: true,
  error: null,
};
let mockHealth: Health = {
  backend: true,
  mode: "browser-preview",
  power_monitor: true,
  power_monitor_degraded: false,
  f8_hotkey: true,
  overlay_available: true,
  driver_installed: true,
  driver_loaded: true,
};
let mockTick = 0;

function mockEmit(event: string, payload: any): void {
  subscribers.forEach((subscriber) => subscriber({
    type: "event",
    event,
    payload,
    timestamp: new Date().toISOString(),
  }));
}

async function mockRpc<T>(method: string, params: Record<string, unknown>): Promise<T> {
  await new Promise((resolve) => window.setTimeout(resolve, 30));
  switch (method) {
    case "get_bootstrap":
    case "bootstrap":
      return {
        protocol_version: 2,
        app_name: "HeroFlow Desktop",
        config: mockConfig,
        heroes: MOCK_HEROES,
        state: mockState,
        health: mockHealth,
      } as T;
    case "get_app_state": {
      mockTick += 1;
      const active = mockState.status === "running";
      mockState = {
        ...mockState,
        power: active ? 150 + Math.sin(mockTick / 2) * 28 : 112 + Math.sin(mockTick / 3) * 5,
        energy: mockState.energy + (active ? 0.00005 : 0.00001),
      };
      return mockState as T;
    }
    case "save_config":
      mockConfig = { ...mockConfig, ...((params.config as Partial<Config>) || params) };
      return mockConfig as T;
    case "reset_config":
      mockConfig = {
        ...mockConfig,
        overlay_enabled: false,
        mouse_speed: 500,
        auto_shutdown: "none",
        unlimited_mode: false,
        schedule_mode: "immediate",
        duration_seconds: 3600,
        selected_heroes: ["D.Va"],
        hero_ratios: { "D.Va": 100 },
      };
      return mockConfig as T;
    case "start_flow":
    case "start_loop": {
      const scheduled = params.schedule_mode === "scheduled";
      mockState = {
        ...mockState,
        status: scheduled ? "scheduled" : "running",
        running: !scheduled,
        paused: false,
        mode: method === "start_loop" ? "loop" : "flow",
        scheduled_for: scheduled ? String(params.start_at || "") : null,
        started_at: scheduled ? null : Date.now() / 1000,
        current_step: scheduled ? "" : "等待游戏窗口就绪",
        next_step: scheduled ? "" : "识别开始按钮",
      };
      mockEmit("state_snapshot", mockState);
      mockEmit("log_entry", { level: "INFO", message: scheduled ? "任务已加入预约队列" : "模拟自动化任务已启动", timestamp: new Date().toISOString() });
      return mockState as T;
    }
    case "pause_flow":
      mockState = { ...mockState, status: "paused", running: true, paused: true };
      mockEmit("state_snapshot", mockState);
      return mockState as T;
    case "resume_flow":
      mockState = { ...mockState, status: "running", running: true, paused: false };
      mockEmit("state_snapshot", mockState);
      return mockState as T;
    case "stop_flow":
    case "stop_loop":
    case "cancel_schedule":
      mockState = { ...mockState, status: "idle", running: false, paused: false, scheduled_for: null, current_step: "", next_step: "" };
      mockEmit("state_snapshot", mockState);
      mockEmit("log_entry", { level: "WARN", message: "任务已安全停止", timestamp: new Date().toISOString() });
      return mockState as T;
    case "confirm_dangerous_action":
      return { token: "browser-preview-confirmation" } as T;
    case "get_health":
    case "check_dependencies":
      return mockHealth as T;
    case "check_driver":
      return { installed: mockHealth.driver_installed, loaded: mockHealth.driver_loaded } as T;
    case "install_driver":
      mockHealth = { ...mockHealth, driver_installed: true, driver_loaded: true };
      mockEmit("driver_install_finished", { ok: true, message: "模拟驱动检查完成" });
      return { ok: true, message: "模拟驱动检查完成", requires_restart: false } as T;
    case "refresh_tariff":
    case "get_tariff":
      return { province: "上海", price: [0.617, 0.667, 0.917][Number(params.tier || 1) - 1], source: "preview" } as T;
    case "toggle_overlay":
      mockConfig = { ...mockConfig, overlay_enabled: Boolean(params.enabled) };
      mockState = { ...mockState, overlay_enabled: Boolean(params.enabled) };
      return { enabled: Boolean(params.enabled) } as T;
    default:
      throw new Error(`模拟后端不支持：${method}`);
  }
}

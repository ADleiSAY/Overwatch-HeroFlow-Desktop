export type RunStatus = "idle" | "scheduled" | "starting" | "running" | "paused" | "stopping" | "completed" | "error";

export interface Hero {
  name: string;
  display_name: string;
  category: string;
  image: string;
}

export interface Config {
  schema_version: number;
  overlay_enabled: boolean;
  mouse_speed: number;
  auto_shutdown: "none" | "stop_only" | "shutdown" | "both";
  unlimited_mode: boolean;
  schedule_mode: "immediate" | "scheduled";
  start_at: string;
  end_at: string;
  duration_seconds: number;
  selected_heroes: string[];
  hero_ratios: Record<string, number>;
  tariff_tier: number;
  custom_tariff: string;
}

export interface AppState {
  status: RunStatus;
  running: boolean;
  paused: boolean;
  mode: "flow" | "loop";
  current_step: string;
  next_step: string;
  scheduled_for: string | null;
  started_at: number | null;
  power: number;
  energy: number;
  average_power: number;
  degraded_power: boolean;
  overlay_enabled: boolean;
  hotkey_registered: boolean;
  error: { code: string; message: string } | null;
}

export interface Health {
  backend: boolean;
  mode: string;
  power_monitor: boolean;
  power_monitor_degraded: boolean;
  f8_hotkey: boolean;
  overlay_available: boolean;
  driver_installed: boolean;
  driver_loaded: boolean;
}

export interface DriverInstallProgress {
  active: boolean;
  progress: number;
  phase: string;
  message: string;
  status: "idle" | "working" | "success" | "error";
}

export interface LogEntry {
  level: string;
  message: string;
  timestamp: string;
}

export interface Bootstrap {
  protocol_version: number;
  app_name: string;
  config: Config;
  heroes: Hero[];
  state: AppState;
  health: Health;
}

export interface RpcMessage {
  type: "response" | "event";
  id?: number;
  ok?: boolean;
  result?: unknown;
  error?: { code?: string; message?: string };
  event?: string;
  payload?: any;
  timestamp?: string;
}

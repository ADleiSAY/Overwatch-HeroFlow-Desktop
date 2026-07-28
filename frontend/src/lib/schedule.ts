import type { Config } from "../types";

export type RunOptions = Config & Record<string, unknown> & {
  duration_s: number | null;
  confirmation_token?: string;
};

export function buildRunOptions(
  config: Config,
  loop: boolean,
  confirmationToken?: string,
): RunOptions {
  return {
    ...config,
    duration_s: config.unlimited_mode ? null : config.duration_seconds,
    confirmation_token: confirmationToken,
    auto_shutdown: loop ? "none" : config.auto_shutdown,
  };
}

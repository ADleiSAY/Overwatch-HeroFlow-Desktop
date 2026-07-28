import assert from "node:assert/strict";
import test from "node:test";
import { buildRunOptions } from "../src/lib/schedule.ts";
import type { Config } from "../src/types.ts";

const config: Config = {
  schema_version: 2,
  overlay_enabled: false,
  mouse_speed: 500,
  auto_shutdown: "both",
  unlimited_mode: false,
  schedule_mode: "scheduled",
  start_at: "2030-01-02T03:04:05",
  end_at: "2030-01-02T04:04:05",
  duration_seconds: 3600,
  selected_heroes: ["D.Va"],
  hero_ratios: { "D.Va": 100 },
  tariff_tier: 1,
  custom_tariff: "0.52",
};

test("preserves the user-selected schedule when starting", () => {
  const options = buildRunOptions(config, false, "confirmed");

  assert.equal(options.start_at, config.start_at);
  assert.equal(options.end_at, config.end_at);
  assert.equal(options.duration_s, 3600);
  assert.equal(options.confirmation_token, "confirmed");
});

test("loop mode keeps its schedule and disables end actions", () => {
  const options = buildRunOptions(config, true);

  assert.equal(options.start_at, config.start_at);
  assert.equal(options.end_at, config.end_at);
  assert.equal(options.auto_shutdown, "none");
});

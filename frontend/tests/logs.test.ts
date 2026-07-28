import assert from "node:assert/strict";
import test from "node:test";
import { collapseRepeatedLogs } from "../src/lib/logs.ts";
import type { LogEntry } from "../src/types.ts";

function entry(message: string, index: number, level = "INFO"): LogEntry {
  return {
    level,
    message,
    timestamp: `2026-07-26T12:00:0${index}.000`,
  };
}

test("keeps one or two matching messages as individual rows", () => {
  const logs = [entry("等待", 1), entry("等待", 2)];

  assert.deepEqual(
    collapseRepeatedLogs(logs).map(({ message, repeatCount }) => ({ message, repeatCount })),
    [
      { message: "等待", repeatCount: 1 },
      { message: "等待", repeatCount: 1 },
    ],
  );
});

test("collapses three or more consecutive matching messages", () => {
  const logs = [
    entry("等待", 1),
    entry("等待", 2),
    entry("等待", 3),
    entry("等待", 4),
  ];

  const result = collapseRepeatedLogs(logs);

  assert.equal(result.length, 1);
  assert.equal(result[0].repeatCount, 4);
  assert.equal(result[0].timestamp, logs[3].timestamp);
});

test("does not merge messages separated by another event or level", () => {
  const logs = [
    entry("等待", 1),
    entry("其他事件", 2),
    entry("等待", 3),
    entry("等待", 4, "WARN"),
    entry("等待", 5, "WARN"),
    entry("等待", 6, "WARN"),
  ];

  assert.deepEqual(
    collapseRepeatedLogs(logs).map(({ level, message, repeatCount }) => ({
      level,
      message,
      repeatCount,
    })),
    [
      { level: "INFO", message: "等待", repeatCount: 1 },
      { level: "INFO", message: "其他事件", repeatCount: 1 },
      { level: "INFO", message: "等待", repeatCount: 1 },
      { level: "WARN", message: "等待", repeatCount: 3 },
    ],
  );
});

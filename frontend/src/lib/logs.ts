import type { LogEntry } from "../types";

export interface DisplayLogEntry extends LogEntry {
  repeatCount: number;
}

const COLLAPSE_THRESHOLD = 3;

export function collapseRepeatedLogs(logs: LogEntry[]): DisplayLogEntry[] {
  const displayed: DisplayLogEntry[] = [];

  for (let index = 0; index < logs.length;) {
    const first = logs[index];
    let end = index + 1;

    while (
      end < logs.length
      && logs[end].level === first.level
      && logs[end].message === first.message
    ) {
      end += 1;
    }

    const repeatCount = end - index;
    if (repeatCount >= COLLAPSE_THRESHOLD) {
      displayed.push({ ...logs[end - 1], repeatCount });
    } else {
      for (let current = index; current < end; current += 1) {
        displayed.push({ ...logs[current], repeatCount: 1 });
      }
    }

    index = end;
  }

  return displayed;
}

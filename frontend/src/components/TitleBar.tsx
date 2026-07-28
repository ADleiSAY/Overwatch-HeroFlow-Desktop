import { getCurrentWindow } from "@tauri-apps/api/window";
import type { MouseEvent } from "react";
import appIcon from "../../../icon/icon.ico?url";
import { Icon } from "./Icon";
import { isTauriRuntime } from "../lib/rpc";

export function TitleBar({ online }: { online: boolean }) {
  const appWindow = isTauriRuntime ? getCurrentWindow() : null;
  const startDragging = (event: MouseEvent<HTMLElement>) => {
    if (!appWindow || event.button !== 0) return;
    if ((event.target as HTMLElement).closest("button")) return;
    void appWindow.startDragging();
  };
  const toggleMaximize = (event: MouseEvent<HTMLElement>) => {
    if (!appWindow || (event.target as HTMLElement).closest("button")) return;
    void appWindow.toggleMaximize();
  };
  return (
    <header className="titlebar" data-tauri-drag-region onMouseDown={startDragging} onDoubleClick={toggleMaximize}>
      <div className="brand" data-tauri-drag-region>
        <img src={appIcon} alt="" />
        <div data-tauri-drag-region>
          <b>HEROFLOW</b>
          <small>{online ? "SYSTEM ONLINE" : "CONNECTING"}</small>
        </div>
      </div>
      <div className="window-controls">
        <button aria-label="最小化" disabled={!appWindow} onClick={() => appWindow?.minimize()}><Icon name="minimize" /></button>
        <button aria-label="最大化" disabled={!appWindow} onClick={() => appWindow?.toggleMaximize()}><Icon name="maximize" /></button>
        <button className="close" aria-label="关闭" disabled={!appWindow} onClick={() => appWindow?.close()}><Icon name="close" /></button>
      </div>
    </header>
  );
}

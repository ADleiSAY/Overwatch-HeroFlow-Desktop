#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs::OpenOptions;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tauri::{Emitter, Manager};

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

struct Backend {
    child: Arc<Mutex<Option<Child>>>,
    startup_error: Arc<Mutex<Option<String>>>,
    startup_status: Arc<Mutex<StartupStatus>>,
}

struct StartupStatus {
    phase: String,
    message: String,
    progress: u8,
    ready: bool,
}

impl StartupStatus {
    fn launching() -> Self {
        Self {
            phase: "launcher".to_string(),
            message: "正在启动 HeroFlow Core".to_string(),
            progress: 5,
            ready: false,
        }
    }
}

fn append_diagnostic(path: &Path, message: &str) {
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(file, "{message}");
    }
}

#[tauri::command]
fn backend_request(state: tauri::State<'_, Backend>, request: String) -> Result<(), String> {
    let mut guard = state.child.lock().map_err(|error| error.to_string())?;
    let child = guard.as_mut().ok_or_else(|| {
        state
            .startup_error
            .lock()
            .ok()
            .and_then(|value| value.clone())
            .unwrap_or_else(|| "backend is unavailable".to_string())
    })?;
    let stdin = child.stdin.as_mut().ok_or("sidecar stdin unavailable")?;
    stdin
        .write_all(request.as_bytes())
        .and_then(|_| stdin.write_all(b"\n"))
        .and_then(|_| stdin.flush())
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn backend_status(state: tauri::State<'_, Backend>) -> serde_json::Value {
    let mut available = false;
    let mut exit_error = None;
    if let Ok(mut guard) = state.child.lock() {
        let mut clear_child = false;
        if let Some(child) = guard.as_mut() {
            match child.try_wait() {
                Ok(Some(status)) => {
                    clear_child = true;
                    exit_error = Some(format!("HeroFlow Core 已退出（{status}）"));
                }
                Ok(None) => available = true,
                Err(error) => exit_error = Some(format!("无法读取后端状态：{error}")),
            }
        }
        if clear_child {
            *guard = None;
        }
    }
    if let Some(message) = exit_error {
        if let Ok(mut error) = state.startup_error.lock() {
            *error = Some(message.clone());
        }
        if let Ok(mut status) = state.startup_status.lock() {
            status.ready = false;
            status.phase = "error".to_string();
            status.message = message;
        }
    }
    let error = state.startup_error.lock().ok().and_then(|value| value.clone());
    let status = state.startup_status.lock().ok();
    serde_json::json!({
        "available": available,
        "ready": status.as_ref().map(|value| value.ready).unwrap_or(false) && available,
        "phase": status.as_ref().map(|value| value.phase.clone()).unwrap_or_else(|| "unknown".to_string()),
        "message": status.as_ref().map(|value| value.message.clone()).unwrap_or_else(|| "正在读取启动状态".to_string()),
        "progress": status.as_ref().map(|value| value.progress).unwrap_or(0),
        "error": error
    })
}

fn resolve_executable(resource_dir: &Path, current_dir: &Path, name: &str) -> Result<PathBuf, String> {
    let executable_dir = std::env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(Path::to_path_buf));
    let mut candidates = vec![
        resource_dir.join(format!("{name}.exe")),
        resource_dir.join(format!("{name}-x86_64-pc-windows-msvc.exe")),
        current_dir.join("src-tauri").join("binaries").join(format!("{name}-x86_64-pc-windows-msvc.exe")),
        current_dir.join("frontend").join("src-tauri").join("binaries").join(format!("{name}-x86_64-pc-windows-msvc.exe")),
    ];
    if let Some(directory) = executable_dir {
        candidates.insert(0, directory.join(format!("{name}.exe")));
        candidates.insert(1, directory.join(format!("{name}-x86_64-pc-windows-msvc.exe")));
    }
    candidates
        .iter()
        .find(|path| path.is_file())
        .cloned()
        .ok_or_else(|| {
            format!(
                "{name} sidecar not found; checked: {}",
                candidates.iter().map(|path| path.display().to_string()).collect::<Vec<_>>().join(", ")
            )
        })
}

fn spawn_backend(
    backend_path: &Path,
    overlay_path: Option<&Path>,
    app_data_dir: &Path,
    heroes_dir: &Path,
    legacy_config: &Path,
) -> Result<Child, String> {
    let mut command = Command::new(backend_path);
    command
        .arg("--data-dir").arg(app_data_dir)
        .arg("--legacy-config").arg(legacy_config)
        .arg("--heroes-dir").arg(heroes_dir);
    if let Some(path) = overlay_path {
        command.arg("--overlay-bin").arg(path);
    }
    #[cfg(target_os = "windows")]
    command.creation_flags(CREATE_NO_WINDOW);
    command
        .current_dir(app_data_dir)
        .env("HEROFLOW_DATA_DIR", app_data_dir)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| format!("unable to launch {}: {error}", backend_path.display()))
}

fn main() {
    let app = tauri::Builder::default()
        .setup(|app| {
            let resource_dir = app.path().resource_dir().map_err(|error| error.to_string())?;
            let app_data_dir = app.path().app_data_dir().map_err(|error| error.to_string())?;
            std::fs::create_dir_all(&app_data_dir).map_err(|error| error.to_string())?;
            let current_dir = std::env::current_dir().map_err(|error| error.to_string())?;
            let heroes_dir = if resource_dir.join("heroes").exists() {
                resource_dir.join("heroes")
            } else if current_dir.join("public").join("heroes").exists() {
                current_dir.join("public").join("heroes")
            } else {
                current_dir.join("frontend").join("public").join("heroes")
            };
            let legacy_config = if current_dir.join("config.json").exists() {
                current_dir.join("config.json")
            } else {
                current_dir.parent().unwrap_or(&current_dir).join("config.json")
            };
            let child_state = Arc::new(Mutex::new(None));
            let error_state = Arc::new(Mutex::new(None));
            let status_state = Arc::new(Mutex::new(StartupStatus::launching()));
            let diagnostic_path = app_data_dir.join("backend-startup.log");
            let _ = std::fs::write(&diagnostic_path, "HeroFlow Core startup\n");

            let launch_result = resolve_executable(&resource_dir, &current_dir, "backend")
                .and_then(|backend_path| {
                    append_diagnostic(
                        &diagnostic_path,
                        &format!("backend={}", backend_path.display()),
                    );
                    let overlay_path = resolve_executable(&resource_dir, &current_dir, "overlay").ok();
                    spawn_backend(
                        &backend_path,
                        overlay_path.as_deref(),
                        &app_data_dir,
                        &heroes_dir,
                        &legacy_config,
                    )
                });

            match launch_result {
                Ok(mut child) => {
                    append_diagnostic(&diagnostic_path, &format!("spawned pid={}", child.id()));
                    let stdout = child.stdout.take().ok_or("sidecar stdout unavailable")?;
                    let stderr = child.stderr.take().ok_or("sidecar stderr unavailable")?;
                    *child_state.lock().map_err(|error| error.to_string())? = Some(child);

                    let output_handle = app.handle().clone();
                    let output_status = status_state.clone();
                    let output_error = error_state.clone();
                    let output_log = diagnostic_path.clone();
                    std::thread::spawn(move || {
                        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                            if let Ok(value) = serde_json::from_str::<serde_json::Value>(&line) {
                                if value.get("type").and_then(|item| item.as_str()) == Some("event") {
                                    match value.get("event").and_then(|item| item.as_str()) {
                                        Some("startup_progress") => {
                                            if let Some(payload) = value.get("payload") {
                                                if let Ok(mut status) = output_status.lock() {
                                                    status.progress = payload
                                                        .get("progress")
                                                        .and_then(|item| item.as_u64())
                                                        .unwrap_or(status.progress as u64)
                                                        .min(100) as u8;
                                                    status.phase = payload
                                                        .get("phase")
                                                        .and_then(|item| item.as_str())
                                                        .unwrap_or(&status.phase)
                                                        .to_string();
                                                    status.message = payload
                                                        .get("message")
                                                        .and_then(|item| item.as_str())
                                                        .unwrap_or(&status.message)
                                                        .to_string();
                                                }
                                            }
                                        }
                                        Some("backend_ready") => {
                                            if let Ok(mut status) = output_status.lock() {
                                                status.ready = true;
                                                status.progress = 90;
                                                status.phase = "ready".to_string();
                                                status.message = "核心服务已就绪，正在读取配置与驱动状态".to_string();
                                            }
                                        }
                                        _ => {}
                                    }
                                }
                                let _ = output_handle.emit("backend-message", value);
                            }
                        }
                        let message = "HeroFlow Core 输出通道已关闭".to_string();
                        append_diagnostic(&output_log, &message);
                        if let Ok(mut status) = output_status.lock() {
                            status.ready = false;
                            status.phase = "error".to_string();
                            status.message = message.clone();
                        }
                        if let Ok(mut error) = output_error.lock() {
                            *error = Some(message);
                        }
                        let _ = output_handle.emit("backend-disconnected", ());
                    });
                    let error_handle = app.handle().clone();
                    let error_log = diagnostic_path.clone();
                    std::thread::spawn(move || {
                        for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                            append_diagnostic(&error_log, &format!("stderr: {line}"));
                            let _ = error_handle.emit("backend-diagnostic", line);
                        }
                    });
                }
                Err(error) => {
                    let message = format!("HeroFlow Core 启动失败：{error}");
                    let _ = std::fs::write(app_data_dir.join("startup-error.log"), &message);
                    append_diagnostic(&diagnostic_path, &message);
                    *error_state.lock().map_err(|lock_error| lock_error.to_string())? = Some(message);
                    if let Ok(mut status) = status_state.lock() {
                        status.phase = "error".to_string();
                        status.message = error_state
                            .lock()
                            .ok()
                            .and_then(|value| value.clone())
                            .unwrap_or_else(|| "HeroFlow Core 启动失败".to_string());
                    }
                }
            }
            app.manage(Backend {
                child: child_state,
                startup_error: error_state,
                startup_status: status_state,
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![backend_request, backend_status])
        .build(tauri::generate_context!())
        .expect("failed to build HeroFlow Desktop");

    app.run(|handle, event| {
        if matches!(event, tauri::RunEvent::ExitRequested { .. }) {
            if let Some(state) = handle.try_state::<Backend>() {
                if let Ok(mut guard) = state.child.lock() {
                    if let Some(child) = guard.as_mut() {
                        if let Some(stdin) = child.stdin.as_mut() {
                            let _ = stdin.write_all(
                                b"{\"id\":0,\"version\":2,\"method\":\"shutdown_app\",\"params\":{}}\n",
                            );
                            let _ = stdin.flush();
                        }
                        let deadline = Instant::now() + Duration::from_millis(900);
                        while Instant::now() < deadline {
                            if child.try_wait().ok().flatten().is_some() {
                                return;
                            }
                            std::thread::sleep(Duration::from_millis(50));
                        }
                        let _ = child.kill();
                    }
                }
            }
        }
    });
}

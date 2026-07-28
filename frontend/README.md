# Overwatch Hero UI

This is the React + TypeScript frontend for the Tauri desktop shell.

## Development

```powershell
npm install
npm run build
```

The production desktop build expects the Python sidecar at
`src-tauri/binaries/backend-x86_64-pc-windows-msvc.exe`. Build it from the
repository root with `scripts/build_sidecar.ps1`.

The sidecar communicates over newline-delimited JSON. Requests are sent with
`backend_request`; responses and events are emitted as `backend-message`.

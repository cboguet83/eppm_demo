# Runtime mode and source watching

Start the application with `python -m scripts.run_app`. Docker and Compose use
this launcher automatically. It resolves the source watcher before Streamlit
starts, then launches the existing authenticated `asgi_app.py` entrypoint.

OIDC sign-in, roles and server-side authorization remain mandatory in every mode.
`APP_RUN_MODE` controls performance settings only; `APP_ENV` continues to control
security requirements. A local demo can keep `APP_ENV=development` and its local
OIDC provider. Production still requires the existing HTTPS and MFA settings.

| `APP_RUN_MODE` | Source watching |
|---|---|
| `auto` (default) | Enabled for `APP_ENV=development`; disabled for staging/production |
| `development` | Enabled (`auto` backend) |
| `demo` | Disabled |
| `production` | Disabled |

An empty `APP_FILE_WATCHER_TYPE` follows the mode. Set it explicitly to `auto`,
`none`, `poll` or `watchdog` to override the mode. Additional Streamlit CLI options
are forwarded; an explicit `--server.fileWatcherType` option overrides the default.
Invalid modes/backends stop startup with a configuration error.

## Local Docker use

Set `APP_RUN_MODE=auto` in `.local/oidc.env` for development, or
`APP_RUN_MODE=demo` for demos. Leave `APP_FILE_WATCHER_TYPE` empty unless an
override is needed. The local configuration generator includes these defaults
in newly generated files; existing credentials and configuration are preserved.
Ordinary Compose deployments can set the same values in `.env` or the shell.

Recreate the app after changing environment settings:

```powershell
docker compose --env-file .local/oidc.env -f docker-compose.yml -f docker-compose.oidc.yml up -d --no-deps --force-recreate app
```

For a temporary demo setting, set `$env:APP_RUN_MODE='demo'` before that command.
Shell variables take precedence over the Compose environment file. Set it back
to `auto` and recreate to restore development watching.

A restart alone does not reload environment settings. With watching disabled,
restart the app after source edits. Widget callbacks, page navigation, data
updates and normal application reruns still work.

The former no-watch Compose overlay has been removed; use `APP_RUN_MODE=demo`
to disable watching.

## Native Python use

Export the existing authentication/application variables into the process
environment, then run:

```powershell
$env:APP_RUN_MODE='development' # Use 'demo' to disable source watching.
python -m scripts.run_app
```

The launcher does not load `.env` files itself. Calling `streamlit run` directly
bypasses this mode resolver; use the launcher to apply these parameters.

See [the measured watcher comparison](file-watcher-comparison.md) for first-load
and scrolling results. Mode selection does not change cache keys or page loading.

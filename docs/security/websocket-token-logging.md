# WebSocket Auth Token in Query Strings

**Status:** documented operational risk; no code change required.
**Audit reference:** F-S-19 (audit/2026-04-29).

## Summary

When `API_AUTH_TOKEN` is configured, the Drevalis backend authenticates
WebSocket connections via the `?token=...` query parameter:

```
src/drevalis/api/websocket.py:69
ws_token = websocket.query_params.get("token", "")
```

This is intentional: browser WebSocket APIs cannot set arbitrary
`Authorization` headers, so the only portable place to carry a bearer
token through `WebSocket()` construction is the URL itself. The token
is compared with `secrets.compare_digest`, so the comparison is safe.

The risk is downstream: **most reverse proxies and access logs record
full URLs by default**, including query strings. A misconfigured
nginx, Apache, or HAProxy logfile will write the API token to disk on
every WS connection and on every reconnect, where it can leak via:

- Log rotation that ships off-host (logrotate → SFTP, Promtail, Vector,
  Datadog, Splunk).
- Backup snapshots that include `/var/log/`.
- Operator-initiated `tail -f` shared in chat, screenshots, or PRs.
- Browser DevTools "Network" tab when the operator records a HAR file.

## What operators need to do

If you have set `API_AUTH_TOKEN`, configure your reverse proxy to
strip the `token` query parameter from access logs **before** it lands
on disk.

### Nginx

```nginx
# Remove the token from the logged URI for /ws/ endpoints.
map $request_uri $clean_request_uri {
    "~^(?<base>/ws/[^?]*).*token=[^&]*(?<rest>.*)" $base$rest;
    default                                        $request_uri;
}

log_format ws_safe '$remote_addr - $remote_user [$time_local] '
                   '"$request_method $clean_request_uri $server_protocol" '
                   '$status $body_bytes_sent';

access_log /var/log/nginx/ws.log ws_safe;
```

### Caddy

```caddy
log {
    format filter {
        wrap json
        fields {
            uri query {
                replace token REDACTED
            }
        }
    }
}
```

### Nginx Proxy Manager (the production fronting host)

NPM uses the same nginx underneath. Add a "Custom Nginx Configuration"
block on the host with the `map` + `log_format` snippets above.

## What we won't change in code

- **Don't move the token to `Sec-WebSocket-Protocol`.** Browsers do
  permit setting that header at construction time, but it is then
  echoed back to the client during the handshake, exposing it to any
  middleware that logs response headers — same problem, different log
  line. The query-string approach concentrates the leakage to one
  predictable place that operators can scrub.
- **Don't add a separate WS-only token.** That doubles the secret
  surface area without changing the handshake-logging concern.
- **Don't move auth into a first-message exchange after `accept()`.**
  This works but means `wss://...` connections that fail auth still
  get a successful TLS handshake plus a successful WS upgrade plus a
  custom close frame — operationally noisier than a 403 at the gate,
  and harder to alert on.

## When to revisit

If we ever add a customer-facing public WS endpoint (today every WS
endpoint is admin-side), this doc + the per-proxy scrubber is no
longer enough — the protocol-level handshake design needs to change.
Track that in a new ADR.

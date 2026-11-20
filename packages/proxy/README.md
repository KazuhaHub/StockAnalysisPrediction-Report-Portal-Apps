# packages/proxy

The application side of the Portal reviewed forward proxy (Portal doc 184).

A backend container has no network. When its release declares `network.proxy`,
the runner sets `HTTPS_PROXY`/`https_proxy` to `http://127.0.0.1:3128`,
`NO_PROXY`/`no_proxy` to `127.0.0.1,localhost` and `PORTAL_APP_PROXY_LISTEN`. It
does not set `HTTP_PROXY`. This package supplies the forwarder that answers on
that address:

- `proxy.Serve(ctx, proxy.Options{})`: a library for backends with a resident Go
  process. It blocks until `ctx` is done. `proxy.Listen` binds the loopback
  address first, for a host that must have the port open before it starts
  workers; pass the result as `Options.Listener`.
- `cmd/portal-egress-proxy`: the same, as a static binary
  (`CGO_ENABLED=0 go build ./cmd/portal-egress-proxy`).

It accepts only HTTP/1.1 `CONNECT host:port` and answers anything else with 405.
Each CONNECT opens a `PRXY0001` stream on `PORTAL_APP_BROKER_SOCKET`; success
answers `200 Connection established` and splices both ways, passing half-close
on. A broker refusal becomes `403` with `X-Portal-Proxy-Refusal: <code>` and no
body. The forwarder holds no authority: every decision is the broker's, and
without an administrator's review every CONNECT is refused.

The wire codec (`wire.go`) mirrors `internal/appplatform/proxyforwarder` in the
Portal repository byte for byte; `wire_test.go` pins vectors taken from it.

package main

import (
	"context"
	"errors"
	"net/http"
	"net/url"
	"os"
	"time"

	"github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/proxy"
)

// Outbound HTTPS is opt-in. A backend container has no network. A release that
// declares the network.proxy capability gets a forwarder on its own loopback
// (packages/proxy) that tunnels each CONNECT to a host an administrator has
// reviewed; the runner sets PORTAL_APP_PROXY_LISTEN and HTTPS_PROXY only for
// such a release. Nothing here runs for an app that does not declare it.

// proxyConfigured reports whether the runner asked for the forwarder.
func proxyConfigured(getenv func(string) string) bool {
	return getenv(proxy.EnvProxyListen) != "" && getenv(proxy.EnvBrokerSocket) != ""
}

// startEgressProxy binds the forwarder's port before it returns, so work
// started afterwards can already use it. It does nothing, and returns a no-op
// stop, when the release does not declare network.proxy. The forwarder holds no
// authority: until an administrator has reviewed the hosts every CONNECT is
// refused with 403.
func startEgressProxy() (stop func(), err error) {
	if !proxyConfigured(os.Getenv) {
		return func() {}, nil
	}
	l, err := proxy.Listen(proxy.Options{})
	if err != nil {
		return nil, err
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		defer close(done)
		_ = proxy.Serve(ctx, proxy.Options{Listener: l})
	}()
	return func() { cancel(); <-done }, nil
}

// RefusalError is a CONNECT the broker refused. Code is the value of the
// X-Portal-Proxy-Refusal header: not_granted, host_not_reviewed,
// port_not_permitted, address_denied, resolve_failed, connect_failed, busy,
// budget_spent or unavailable.
type RefusalError struct{ Code string }

func (e *RefusalError) Error() string { return "proxy refused the tunnel: " + e.Code }

// newEgressClient returns an HTTP client for reviewed HTTPS hosts. Pass
// http.ProxyFromEnvironment in the service. Only https works: the runner sets
// no HTTP_PROXY, so a plain http request has no way out and is refused here
// first. Redirects are not followed, because a redirect could name a host that
// was not reviewed.
func newEgressClient(proxyFunc func(*http.Request) (*url.URL, error)) *http.Client {
	transport := &http.Transport{
		Proxy: proxyFunc,
		// Go drops a refused CONNECT's headers; read the reason before it does.
		OnProxyConnectResponse: func(_ context.Context, _ *url.URL, _ *http.Request, res *http.Response) error {
			if res.StatusCode != http.StatusOK {
				code := res.Header.Get("X-Portal-Proxy-Refusal")
				if code == "" {
					code = "none" // not the broker's refusal, e.g. the forwarder's own 405
				}
				return &RefusalError{Code: code}
			}
			return nil
		},
		TLSHandshakeTimeout:    10 * time.Second,
		ResponseHeaderTimeout:  20 * time.Second,
		MaxResponseHeaderBytes: 64 << 10,
		DisableKeepAlives:      true,
	}
	return &http.Client{
		Transport: roundTripper{transport},
		Timeout:   30 * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}
}

type roundTripper struct{ next http.RoundTripper }

func (r roundTripper) RoundTrip(req *http.Request) (*http.Response, error) {
	if req.URL.Scheme != "https" {
		return nil, errors.New("only https is reachable through the proxy")
	}
	return r.next.RoundTrip(req)
}

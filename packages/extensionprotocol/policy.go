package extensionprotocol

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"mime"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"
)

type Route struct {
	Method string `json:"method"`
	Prefix string `json:"prefix"`
}

type Policy struct {
	Routes    []Route        `json:"routes"`
	Ports     []uint16       `json:"ports"`
	Networks  []netip.Prefix `json:"networks"`
	PlainHTTP bool           `json:"plain_http"`
}

var ErrBackend = errors.New("extension backend unavailable or invalid response")
var ErrBusy = errors.New("extension backend capacity unavailable")

func (p Policy) Allows(method, path string) bool {
	if !validRequest(method, path) {
		return false
	}
	u, err := url.ParseRequestURI(path)
	if err != nil {
		return false
	}
	for _, r := range p.Routes {
		prefix := strings.TrimSuffix(r.Prefix, "/")
		if r.Method == method && (u.Path == prefix || strings.HasPrefix(u.Path, prefix+"/")) {
			return true
		}
	}
	return false
}

// AllowsIP never permits local/metadata addresses, even under a broad explicit
// CIDR. Private-network exceptions are scoped to this connection policy only.
func (p Policy) AllowsIP(ip netip.Addr) bool {
	ip = ip.Unmap()
	if !ip.IsValid() || !ip.IsGlobalUnicast() || ip.IsLoopback() || ip.IsLinkLocalUnicast() || ip.IsLinkLocalMulticast() {
		return false
	}
	for _, cidr := range []string{"100.64.0.0/10", "192.0.0.0/24", "198.18.0.0/15", "240.0.0.0/4", "64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32", "::/96"} {
		if netip.MustParsePrefix(cidr).Contains(ip) {
			return false
		}
	}
	if ip.IsPrivate() {
		for _, prefix := range p.Networks {
			if prefix.Contains(ip) {
				return true
			}
		}
		return false
	}
	return !p.PlainHTTP
}

func (p Policy) valid() bool {
	if len(p.Routes) == 0 || len(p.Routes) > 32 || len(p.Ports) == 0 || len(p.Ports) > 16 || len(p.Networks) > 16 || (p.PlainHTTP && len(p.Networks) == 0) {
		return false
	}
	for _, port := range p.Ports {
		if port == 0 {
			return false
		}
	}
	for _, prefix := range p.Networks {
		if !prefix.IsValid() {
			return false
		}
	}
	for _, r := range p.Routes {
		if !validRequest(r.Method, r.Prefix) || strings.Contains(r.Prefix, "?") || strings.Contains(r.Prefix, "%") {
			return false
		}
	}
	return true
}

type BackendResponse struct {
	Status int
	Body   []byte
}
type BackendClient struct {
	base   *url.URL
	policy Policy
	client *http.Client
	slots  chan struct{}
	lookup func(context.Context, string) ([]netip.Addr, error)
	dial   func(context.Context, string, string) (net.Conn, error)
}

func NewBackendClient(rawURL string, policy Policy) (*BackendClient, error) {
	u, err := url.Parse(rawURL)
	if err != nil || !policy.valid() || u.Hostname() == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || (u.Path != "" && u.Path != "/") || (u.Scheme != "https" && !(u.Scheme == "http" && policy.PlainHTTP)) {
		return nil, ErrInvalid
	}
	port := uint16(443)
	if u.Scheme == "http" {
		port = 80
	}
	if u.Port() != "" {
		parsed, e := strconv.ParseUint(u.Port(), 10, 16)
		if e != nil {
			return nil, ErrInvalid
		}
		port = uint16(parsed)
	}
	if !slices.Contains(policy.Ports, port) {
		return nil, ErrInvalid
	}
	policy.Routes = slices.Clone(policy.Routes)
	policy.Ports = slices.Clone(policy.Ports)
	policy.Networks = slices.Clone(policy.Networks)
	c := &BackendClient{base: u, policy: policy, slots: make(chan struct{}, 2)}
	c.lookup = func(ctx context.Context, host string) ([]netip.Addr, error) {
		return net.DefaultResolver.LookupNetIP(ctx, "ip", host)
	}
	c.dial = (&net.Dialer{Timeout: 5 * time.Second}).DialContext
	transport := &http.Transport{Proxy: nil, DialContext: c.dialContext, TLSHandshakeTimeout: 5 * time.Second, ResponseHeaderTimeout: 10 * time.Second, MaxResponseHeaderBytes: 32768, MaxConnsPerHost: 2, IdleConnTimeout: 30 * time.Second}
	c.client = &http.Client{Transport: transport, Timeout: 15 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	return c, nil
}

func (c *BackendClient) dialContext(ctx context.Context, network, address string) (net.Conn, error) {
	host, port, err := net.SplitHostPort(address)
	if err != nil || !strings.EqualFold(host, c.base.Hostname()) {
		return nil, ErrBackend
	}
	n, err := strconv.ParseUint(port, 10, 16)
	if err != nil || !slices.Contains(c.policy.Ports, uint16(n)) {
		return nil, ErrBackend
	}
	ips, err := c.lookup(ctx, host)
	if err != nil || len(ips) == 0 || len(ips) > 32 {
		return nil, ErrBackend
	}
	for _, ip := range ips {
		if !c.policy.AllowsIP(ip) {
			return nil, ErrBackend
		}
	}
	for _, ip := range ips {
		conn, e := c.dial(ctx, network, net.JoinHostPort(ip.Unmap().String(), port))
		if e == nil {
			return conn, nil
		}
		if ctx.Err() != nil {
			break
		}
	}
	return nil, ErrBackend
}

// Do sends only the host-created assertion and JSON data, never incoming cookies
// or caller-controlled headers. It returns a bounded JSON response and safe errors.
func (c *BackendClient) Do(ctx context.Context, method, path string, body []byte, assertion string) (BackendResponse, error) {
	var empty BackendResponse
	if !c.policy.Allows(method, path) || len(body) > 65536 || (method == "GET" && len(body) != 0) || assertion == "" || len(assertion) > maxToken {
		return empty, ErrInvalid
	}
	select {
	case c.slots <- struct{}{}:
		defer func() { <-c.slots }()
	default:
		return empty, ErrBusy
	}
	ref, err := url.ParseRequestURI(path)
	if err != nil {
		return empty, ErrInvalid
	}
	target := c.base.ResolveReference(ref)
	req, err := http.NewRequestWithContext(ctx, method, target.String(), bytes.NewReader(body))
	if err != nil {
		return empty, ErrInvalid
	}
	req.Header.Set(Header, assertion)
	req.Header.Set("Accept", "application/json")
	if len(body) > 0 {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := c.client.Do(req)
	if err != nil {
		return empty, ErrBackend
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 && resp.StatusCode < 400 {
		return empty, ErrBackend
	}
	media, _, err := mime.ParseMediaType(resp.Header.Get("Content-Type"))
	if err != nil || media != "application/json" {
		return empty, ErrBackend
	}
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 1048577))
	if err != nil || len(raw) > 1048576 || !json.Valid(raw) {
		return empty, ErrBackend
	}
	return BackendResponse{Status: resp.StatusCode, Body: raw}, nil
}

func (c *BackendClient) Close() { c.client.CloseIdleConnections() }

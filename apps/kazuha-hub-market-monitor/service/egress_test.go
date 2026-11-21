package main

import (
	"bufio"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// fakeBroker answers every proxy open with a busy refusal, byte for byte.
func fakeBroker(t *testing.T) string {
	t.Helper()
	dir, err := os.MkdirTemp("", "mmb")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(dir) })
	path := filepath.Join(dir, "b.sock")
	l, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { l.Close() })
	go func() {
		for {
			c, err := l.Accept()
			if err != nil {
				return
			}
			go func() {
				defer c.Close()
				buf := make([]byte, len("PRXY0001\x00\x0fexample.com:443"))
				io.ReadFull(c, buf)
				io.WriteString(c, "PRXR0001\x02\x07")
			}()
		}
	}()
	return path
}

func TestEgressProxyListensBeforeItReturns(t *testing.T) {
	t.Setenv("PORTAL_APP_BROKER_SOCKET", fakeBroker(t))
	t.Setenv("PORTAL_APP_PROXY_LISTEN", "127.0.0.1:0")
	addr, stop, err := startEgressProxy()
	if err != nil || addr == "" {
		t.Fatalf("addr %q err %v", addr, err)
	}
	// No retry: the port is bound by the time startEgressProxy returns, so a
	// job started right after it can already use the proxy.
	c, err := net.Dial("tcp", addr)
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	c.SetDeadline(time.Now().Add(5 * time.Second))
	io.WriteString(c, "CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
	resp, err := http.ReadResponse(bufio.NewReader(c), &http.Request{Method: "CONNECT"})
	if err != nil {
		t.Fatal(err)
	}
	if resp.StatusCode != 403 || resp.Header.Get("X-Portal-Proxy-Refusal") != "busy" {
		t.Fatalf("status %d refusal %q", resp.StatusCode, resp.Header.Get("X-Portal-Proxy-Refusal"))
	}
	stop()
	if c2, err := net.Dial("tcp", addr); err == nil {
		c2.Close()
		t.Fatal("the proxy still listens after stop")
	}
}

func TestEgressProxyIsSkippedWithoutABrokerSocket(t *testing.T) {
	t.Setenv("PORTAL_APP_BROKER_SOCKET", "")
	t.Setenv("PORTAL_APP_PROXY_LISTEN", "127.0.0.1:0")
	addr, stop, err := startEgressProxy()
	if err != nil || addr != "" {
		t.Fatalf("addr %q err %v", addr, err)
	}
	stop()
}

func TestEgressProxyRefusesANonLoopbackAddress(t *testing.T) {
	t.Setenv("PORTAL_APP_BROKER_SOCKET", fakeBroker(t))
	t.Setenv("PORTAL_APP_PROXY_LISTEN", "0.0.0.0:3128")
	if _, _, err := startEgressProxy(); err == nil {
		t.Fatal("want an error")
	}
}

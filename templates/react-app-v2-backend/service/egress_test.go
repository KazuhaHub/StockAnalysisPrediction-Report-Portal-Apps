package main

import (
	"errors"
	"net"
	"net/http"
	"net/url"
	"testing"

	"github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/proxy"
)

func TestTheForwarderStartsOnlyWhenTheRunnerAsksForIt(t *testing.T) {
	env := func(values map[string]string) func(string) string {
		return func(name string) string { return values[name] }
	}
	if proxyConfigured(env(nil)) {
		t.Error("no proxy variables: the forwarder must stay off")
	}
	// Portal always sets the broker socket, so the socket alone must not start it.
	if proxyConfigured(env(map[string]string{proxy.EnvBrokerSocket: "/run/portal-app/broker/broker.sock"})) {
		t.Error("the broker socket alone started the forwarder")
	}
	if !proxyConfigured(env(map[string]string{
		proxy.EnvBrokerSocket: "/run/portal-app/broker/broker.sock", proxy.EnvProxyListen: "127.0.0.1:3128"})) {
		t.Error("a declared network.proxy did not start the forwarder")
	}
}

func TestStartEgressProxyIsANoOpWithoutTheCapability(t *testing.T) {
	t.Setenv(proxy.EnvProxyListen, "")
	stop, err := startEgressProxy()
	if err != nil {
		t.Fatal(err)
	}
	stop()
}

func TestEgressClientRefusesPlainHTTP(t *testing.T) {
	_, err := newEgressClient(http.ProxyFromEnvironment).Get("http://example.invalid/")
	if err == nil {
		t.Fatal("plain http was sent")
	}
}

func TestEgressClientReportsTheBrokersRefusalCode(t *testing.T) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	go func() {
		c, err := l.Accept()
		if err != nil {
			return
		}
		defer c.Close()
		buf := make([]byte, 4096)
		_, _ = c.Read(buf)
		_, _ = c.Write([]byte("HTTP/1.1 403 Forbidden\r\nX-Portal-Proxy-Refusal: not_granted\r\nContent-Length: 0\r\n\r\n"))
	}()
	proxyURL, _ := url.Parse("http://" + l.Addr().String())
	_, err = newEgressClient(http.ProxyURL(proxyURL)).Get("https://reviewed.example.com/")
	var refusal *RefusalError
	if !errors.As(err, &refusal) || refusal.Code != "not_granted" {
		t.Fatalf("err %v", err)
	}
}

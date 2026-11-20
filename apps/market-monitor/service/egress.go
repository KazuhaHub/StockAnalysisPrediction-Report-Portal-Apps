package main

import (
	"context"
	"os"

	"github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/proxy"
)

// startEgressProxy starts the reviewed forward proxy's forwarder (Portal doc
// 184) for the Python workers. The port is bound before it returns, so a job
// started afterwards can already use it; the runner points the workers'
// HTTPS_PROXY at the same address. It returns the address, or "" when there is
// no broker socket (a run outside the platform), and a function that stops it
// and closes its tunnels. The forwarder holds no authority: until an
// administrator reviews the hosts, every CONNECT is refused with 403.
func startEgressProxy() (addr string, stop func(), err error) {
	if os.Getenv(proxy.EnvBrokerSocket) == "" {
		return "", func() {}, nil
	}
	l, err := proxy.Listen(proxy.Options{})
	if err != nil {
		return "", nil, err
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		defer close(done)
		// Serve returns only when ctx ends or the listener fails; either way
		// the jobs' CONNECTs are refused (connection refused) and fail.
		_ = proxy.Serve(ctx, proxy.Options{Listener: l})
	}()
	return l.Addr().String(), func() { cancel(); <-done }, nil
}

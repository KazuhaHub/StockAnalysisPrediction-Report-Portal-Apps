// Command portal-egress-proxy is a static forward-proxy forwarder for backends
// without a resident Go process. It listens on PORTAL_APP_PROXY_LISTEN
// (default 127.0.0.1:3128) and relays each CONNECT over the broker socket named
// by PORTAL_APP_BROKER_SOCKET. It holds no authority: every decision is the
// broker's.
package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/proxy"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()
	if err := proxy.Serve(ctx, proxy.Options{}); err != nil {
		fmt.Fprintln(os.Stderr, "portal-egress-proxy:", err)
		stop()
		os.Exit(1)
	}
}

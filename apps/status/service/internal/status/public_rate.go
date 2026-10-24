package status

import (
	"net"
	"net/netip"
	"sync"
	"time"
)

type requestBucket struct {
	tokens float64
	at     time.Time
}
type publicBudget struct {
	mu      sync.Mutex
	origins map[netip.Addr]requestBucket
	total   requestBucket
}

func refillBucket(bucket requestBucket, now time.Time, rate, burst float64) requestBucket {
	if bucket.at.IsZero() {
		return requestBucket{burst, now}
	}
	elapsed := max(0, now.Sub(bucket.at).Seconds())
	return requestBucket{min(burst, bucket.tokens+elapsed*rate), now}
}

// Trust only the socket peer. Edge gateways may enforce a separate client-IP
// policy; caller-supplied forwarding headers never allocate new backend budgets.
func (b *publicBudget) allow(remote string, now time.Time) bool {
	host, _, err := net.SplitHostPort(remote)
	if err != nil {
		return false
	}
	address, err := netip.ParseAddr(host)
	if err != nil {
		return false
	}
	address = address.Unmap()
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.origins == nil {
		b.origins = map[netip.Addr]requestBucket{}
	}
	bucket, exists := b.origins[address]
	if !exists && len(b.origins) >= 1024 {
		for peer, old := range b.origins {
			if now.Sub(old.at) >= time.Minute {
				delete(b.origins, peer)
			}
		}
		if len(b.origins) >= 1024 {
			return false
		}
	}
	bucket = refillBucket(bucket, now, 10, 20)
	b.total = refillBucket(b.total, now, 40, 80)
	if bucket.tokens < 1 || b.total.tokens < 1 {
		b.origins[address] = bucket
		return false
	}
	bucket.tokens--
	b.total.tokens--
	b.origins[address] = bucket
	return true
}

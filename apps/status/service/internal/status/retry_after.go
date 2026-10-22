package status

import (
	"net/http"
	"strconv"
	"strings"
	"time"
)

func retryAfter(value string, now time.Time) time.Duration {
	value = strings.TrimSpace(value)
	if seconds, err := strconv.ParseInt(value, 10, 64); err == nil {
		if seconds <= 0 {
			return 0
		}
		return time.Duration(min(seconds, 3600)) * time.Second
	}
	if date, err := http.ParseTime(value); err == nil {
		return min(time.Hour, max(time.Duration(0), date.Sub(now)))
	}
	return 0
}

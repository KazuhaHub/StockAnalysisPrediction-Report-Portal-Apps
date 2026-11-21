package main

import (
	"log"
	"strconv"
	"syscall"
)

// The installation's /data is an XFS project-quota directory (Portal doc
// 185). The service cannot read the quota from an API, but statfs on such a
// directory reports the quota as the filesystem size and the unused part of
// the quota as free space, so one statfs call yields "used" and "limit" in
// either case: with a quota the limit is the quota, and where /data has none
// (a development run) it is the size of the filesystem holding /data.
const quotaWarnPercent = 80

// fsUsage reports the used and total bytes of the filesystem (or quota
// directory) holding path. It is a variable so tests can supply a fake.
var fsUsage = func(path string) (used, total uint64, err error) {
	var st syscall.Statfs_t
	if err := syscall.Statfs(path, &st); err != nil {
		return 0, 0, err
	}
	block := uint64(st.Bsize)
	total = uint64(st.Blocks) * block
	free := uint64(st.Bfree) * block
	if free > total {
		free = total
	}
	return total - free, total, nil
}

// quotaWarning returns the warning text when /data use has passed 80 % of
// its limit, or "".
func quotaWarning(dataDir string) string {
	used, total, err := fsUsage(dataDir)
	if err != nil || total == 0 || used*100 < total*quotaWarnPercent {
		return ""
	}
	return "data volume use " + percent(used, total) + " of its " + mib(total) + " MiB limit (quota, or the filesystem size when no quota is set); the installation needs a larger quota"
}

func percent(used, total uint64) string {
	return strconv.FormatUint(used*100/total, 10) + " %"
}

func mib(n uint64) string { return strconv.FormatUint(n>>20, 10) }

// warnIfQuotaNearlyUsed logs the warning, if any.
func warnIfQuotaNearlyUsed(dataDir string) {
	if msg := quotaWarning(dataDir); msg != "" {
		log.Printf("market-monitor: warning: %s", msg)
	}
}

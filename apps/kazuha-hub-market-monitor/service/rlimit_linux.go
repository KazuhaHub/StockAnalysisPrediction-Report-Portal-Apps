package main

import (
	"bufio"
	"fmt"
	"os"
	"strings"
	"syscall"
)

// limitMemory caps the process's address space at its current size plus
// headroom bytes, so a crafted file can only make this child fail to allocate.
// The current size matters: a Go process starts with about 1.3 GB of address
// space already reserved (measured; resident memory is about 10 MB), so a
// fixed cap below that, such as 512 MiB, kills even valid files at random.
func limitMemory(headroom uint64) error {
	f, err := os.Open("/proc/self/status")
	if err != nil {
		return err
	}
	defer f.Close()
	var kb uint64
	found := false
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		if rest, ok := strings.CutPrefix(sc.Text(), "VmSize:"); ok {
			if _, err := fmt.Sscanf(strings.TrimSpace(rest), "%d kB", &kb); err != nil {
				return err
			}
			found = true
		}
	}
	if !found {
		return fmt.Errorf("VmSize not found")
	}
	limit := kb<<10 + headroom
	return syscall.Setrlimit(syscall.RLIMIT_AS, &syscall.Rlimit{Cur: limit, Max: limit})
}

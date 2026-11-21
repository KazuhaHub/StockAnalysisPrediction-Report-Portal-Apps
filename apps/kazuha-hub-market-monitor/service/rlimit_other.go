//go:build !linux

package main

// limitMemory is a no-op where the address space cannot be capped (development hosts);
// the container image is Linux.
func limitMemory(uint64) error { return nil }

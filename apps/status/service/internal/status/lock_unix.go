//go:build !windows

package status

import (
	"errors"
	"os"

	"golang.org/x/sys/unix"
)

func lockVolume(path string) (*os.File, error) {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	if err := unix.Flock(int(f.Fd()), unix.LOCK_EX|unix.LOCK_NB); err != nil {
		f.Close()
		return nil, errors.New("status database volume already has an owner")
	}
	return f, nil
}
func releaseVolume(f *os.File) { unix.Flock(int(f.Fd()), unix.LOCK_UN); f.Close() }

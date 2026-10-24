package status

import (
	"context"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"
)

// Deployment mounts only the trusted PostgreSQL socket into this directory.
// Monitor configuration cannot select an arbitrary filesystem path.
const postgresSocketDirectory = "/run/status-postgres"

func postgresSocketPath(directory string, port uint16) (string, error) {
	if !filepath.IsAbs(directory) || filepath.Clean(directory) != directory || port == 0 {
		return "", ErrInvalid
	}
	root, err := os.Lstat(directory)
	if err != nil || !root.IsDir() || root.Mode()&os.ModeSymlink != 0 {
		return "", ErrInvalid
	}
	path := filepath.Join(directory, ".s.PGSQL."+strconv.Itoa(int(port)))
	file, err := os.Lstat(path)
	if err != nil || file.Mode()&os.ModeSocket == 0 || file.Mode()&os.ModeSymlink != 0 {
		return "", ErrInvalid
	}
	return path, nil
}

func postgresSocketConfig(m Monitor, directory string) (*pgx.ConnConfig, error) {
	c := m.Config
	if c.PostgresTransport != "unix" || c.Host != "" || c.URL != "" || c.PlainHTTP || len(c.Networks) != 0 || c.Database == "" {
		return nil, ErrInvalid
	}
	path, err := postgresSocketPath(directory, c.Port)
	if err != nil {
		return nil, err
	}
	// This is an explicit local transport, never a fallback after network TLS fails.
	cfg, err := pgx.ParseConfig("host=/run/status-postgres sslmode=disable")
	if err != nil {
		return nil, err
	}
	cfg.Host, cfg.Port, cfg.Database, cfg.User, cfg.Password = directory, c.Port, c.Database, m.Secret.Username, m.Secret.Password
	cfg.TLSConfig, cfg.Fallbacks = nil, nil
	cfg.ConnectTimeout = 5 * time.Second
	cfg.RuntimeParams["default_transaction_read_only"] = "on"
	cfg.LookupFunc = func(context.Context, string) ([]string, error) { return nil, ErrInvalid }
	cfg.DialFunc = func(ctx context.Context, network, address string) (net.Conn, error) {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		if network != "unix" || address != path {
			return nil, ErrInvalid
		}
		// Recheck on every dial, including driver cleanup/reconnect paths.
		if _, err := postgresSocketPath(directory, c.Port); err != nil {
			return nil, err
		}
		return (&net.Dialer{Timeout: 5 * time.Second}).DialContext(ctx, "unix", path)
	}
	return cfg, nil
}

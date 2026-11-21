package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"sort"
	"strconv"
	"strings"
	"time"
)

// Install-time validation of a history file runs in a child process: the
// service runs itself as `market-monitor validate-history <module> <as_of>`
// with the file on stdin. The child caps its own address space
// (historyChildHeadroom above its start, Linux), fully decodes every column and checks schema,
// metadata, bounds and codes; a crafted file that would exhaust memory kills
// the child, not the service, and the run is refused as output_invalid. The
// parent allows historyChildTimeout and compares the child's report with the
// snapshot's codes.

const (
	// historyChildHeadroom is how much address space the child may add to what
	// it starts with (see limitMemory: a Go process starts with about 1.3 GB
	// reserved). A real file adds about 1 MB; the page-header repro asks for an
	// 843 MB block and dies.
	historyChildHeadroom = 512 << 20
	historyChildTimeout  = 10 * time.Second
	validateHistoryArg   = "validate-history"

	// The child's exit statuses. 1 is a bad file; the Go runtime exits 2 on
	// fatal errors such as running out of memory, which on a capped child is
	// the file's doing. The rest are the environment's.
	exitBadFile     = 1
	exitMemory      = 2
	exitEnvironment = 3
	exitUsage       = 4
)

// errValidatorUnavailable marks a failure of the validation machinery
// (cannot find or start the child, cannot cap it, killed by a signal), as
// opposed to a bad file: the run is reported as validator_unavailable.
var errValidatorUnavailable = errors.New("history validator unavailable")

// historyChildCommand builds the child process; tests replace it.
var historyChildCommand = func(ctx context.Context, module, asOf string) (*exec.Cmd, error) {
	exe, err := os.Executable()
	if err != nil {
		return nil, err
	}
	return exec.CommandContext(ctx, exe, validateHistoryArg, module, asOf), nil
}

// codesDigest is what the child reports and the parent recomputes: the number
// of codes and the SHA-256 of the sorted codes joined by newlines.
func codesDigest(codes []string) string {
	sorted := append([]string(nil), codes...)
	sort.Strings(sorted)
	sum := sha256.Sum256([]byte(strings.Join(sorted, "\n")))
	return strconv.Itoa(len(sorted)) + " " + hex.EncodeToString(sum[:])
}

// runValidateHistory is the child's main: it returns the exit status.
func runValidateHistory(args []string, stdin io.Reader, stdout, stderr io.Writer) int {
	if len(args) != 2 || !historyModules[args[0]] || !validDate(args[1]) {
		fmt.Fprintln(stderr, "usage: market-monitor validate-history <module> <as_of> < file")
		return exitUsage
	}
	module, asOf := args[0], args[1]
	if err := limitMemory(historyChildHeadroom); err != nil {
		fmt.Fprintln(stderr, "memory limit:", err)
		return exitEnvironment
	}
	data, err := io.ReadAll(io.LimitReader(stdin, maxHistoryBytes+1))
	if err != nil {
		fmt.Fprintln(stderr, err)
		return exitEnvironment
	}
	f, err := parseHistory(module, asOf, data)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return exitBadFile
	}
	names := make([]string, len(historySchemas[module]))
	for i, c := range historySchemas[module] {
		names[i] = c.name
	}
	cols, err := readColumns(module, f, names) // every column, not just code
	if err != nil {
		fmt.Fprintln(stderr, err)
		return exitBadFile
	}
	code := cols["code"]
	seen := make(map[string]bool, len(code.ok))
	for i, c := range code.str {
		if !code.ok[i] || c == "" || len(c) > maxCodeLength || seen[c] {
			fmt.Fprintf(stderr, "history row %d code is null, empty, too long or duplicate\n", i)
			return exitBadFile
		}
		seen[c] = true
	}
	fmt.Fprintln(stdout, "ok", codesDigest(code.str))
	return 0
}

// validateHistoryInstall is the install-time check: the child accepts the
// file, and the codes it reports equal the snapshot's.
func validateHistoryInstall(module string, snap *snapshot, data []byte) error {
	if len(data) == 0 || len(data) > maxHistoryBytes {
		return fmt.Errorf("%w: history size", errInvalid)
	}
	ctx, cancel := context.WithTimeout(context.Background(), historyChildTimeout)
	defer cancel()
	cmd, err := historyChildCommand(ctx, module, snap.AsOf)
	if err != nil {
		return fmt.Errorf("%w: %v", errValidatorUnavailable, err)
	}
	var out, errOut bytes.Buffer
	cmd.Stdin, cmd.Stdout, cmd.Stderr = bytes.NewReader(data), &out, &limitedBuffer{buf: &errOut, max: 4096}
	cmd.Env = []string{"GOMAXPROCS=2"} // fewer threads, less address space
	cmd.WaitDelay = time.Second
	if err := cmd.Start(); err != nil {
		return fmt.Errorf("%w: cannot start the child: %v", errValidatorUnavailable, err)
	}
	if err := cmd.Wait(); err != nil {
		reason := strings.TrimSpace(errOut.String())
		var exit *exec.ExitError
		switch {
		case ctx.Err() != nil:
			return fmt.Errorf("%w: history validation timed out", errInvalid)
		case errors.As(err, &exit) && (exit.ExitCode() == exitBadFile || exit.ExitCode() == exitMemory):
			return fmt.Errorf("%w: history validation failed (%v) %s", errInvalid, err, reason)
		default:
			// Signalled, or an exit status that is not a verdict on the file.
			return fmt.Errorf("%w: child failed (%v) %s", errValidatorUnavailable, err, reason)
		}
	}
	codes := make([]string, 0, len(snap.index))
	for c := range snap.index {
		codes = append(codes, c)
	}
	if got := strings.TrimSpace(out.String()); got != "ok "+codesDigest(codes) {
		return fmt.Errorf("%w: history codes differ from the snapshot's", errInvalid)
	}
	return nil
}

type limitedBuffer struct {
	buf *bytes.Buffer
	max int
}

func (l *limitedBuffer) Write(p []byte) (int, error) {
	if room := l.max - l.buf.Len(); room > 0 {
		l.buf.Write(p[:min(len(p), room)])
	}
	return len(p), nil
}

package main

import (
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
)

// Progress and failure reasons for the admin view, both read from a run's log
// so the run index keeps its shape.
//
// A job reports progress by printing, at the start of a line,
// "##progress <done>/<total>" and, while it sleeps before retrying a source,
// "##waiting <unix seconds it resumes>". The last marker in the log tail wins.

const progressTailBytes = 16 << 10

// reasonedRuns is how many of the newest runs get a failure reason in the run
// list: each costs a log read, and the page shows 20 at first.
const reasonedRuns = 50

type AdminProgress struct {
	Done         int    `json:"done"`
	Total        int    `json:"total"`
	WaitingUntil string `json:"waiting_until,omitempty"`
}

func progressOf(log string) *AdminProgress {
	var p *AdminProgress
	waiting := ""
	for _, line := range strings.Split(log, "\n") {
		line = strings.TrimRight(line, "\r")
		if rest, ok := strings.CutPrefix(line, "##progress "); ok {
			done, total, ok := strings.Cut(rest, "/")
			d, err1 := strconv.Atoi(strings.TrimSpace(done))
			n, err2 := strconv.Atoi(strings.TrimSpace(total))
			if !ok || err1 != nil || err2 != nil || n <= 0 || d < 0 || d > n {
				continue
			}
			p, waiting = &AdminProgress{Done: d, Total: n}, ""
		} else if rest, ok := strings.CutPrefix(line, "##waiting "); ok {
			if sec, err := strconv.ParseInt(strings.TrimSpace(rest), 10, 64); err == nil && sec > 0 {
				waiting = time.Unix(sec, 0).UTC().Format(time.RFC3339)
			}
		}
	}
	if p != nil {
		p.WaitingUntil = waiting
	}
	return p
}

// typicalSeconds is the median duration of a job's last five successful runs
// (runs newest first), or 0 when it has none.
func typicalSeconds(runs []Run) int {
	var d []float64
	for _, run := range runs {
		if run.Status != "succeeded" {
			continue
		}
		start, err1 := time.Parse(time.RFC3339, run.StartedAt)
		end, err2 := time.Parse(time.RFC3339, run.FinishedAt)
		if err1 != nil || err2 != nil || end.Before(start) {
			continue
		}
		d = append(d, end.Sub(start).Seconds())
		if len(d) == 5 {
			break
		}
	}
	if len(d) == 0 {
		return 0
	}
	sort.Float64s(d)
	mid := len(d) / 2
	if len(d)%2 == 1 {
		return int(d[mid])
	}
	return int((d[mid-1] + d[mid]) / 2)
}

// Reasons are a closed set the page translates; the detail is the log line
// that shows it, as the job wrote it.
var failureReasons = []string{"timeout", "interrupted", "out_of_memory", "store_incomplete", "quality_gate",
	"source_unavailable", "output_missing", "not_refreshed", "environment", "output_invalid", "service_error", "unknown"}

var (
	oomMarks = []string{"被信号 9", "MemoryError"}
	// A child the OOM killer took: bash reports 137, mm_job "exited -9".
	oomKillMarks = []string{"退出码 137", "pipeline exited -9", "pipeline exited 137"}
	// Only the lines a run ends with: warnings it recovered from do not count.
	sourceMarks = []string{"数据源没有恢复", "本次更新已中止"}
)

func failureReason(run Run, log string) (reason, detail string) {
	if run.Status != "failed" && run.Status != "interrupted" {
		return "", ""
	}
	lines := strings.Split(strings.ReplaceAll(log, "\r", ""), "\n")
	switch run.Error {
	case "interrupted":
		return "interrupted", ""
	case "timeout":
		return "timeout", ""
	case "exit_status":
	case "output_invalid":
		return "output_invalid", lastLine(lines, serviceNote)
	default:
		return "service_error", lastLine(lines, serviceNote)
	}
	switch run.ExitCode {
	case 94:
		return "store_incomplete", lastLine(lines, func(l string) bool {
			return strings.HasPrefix(l, "[mm_job] ") && strings.Contains(l, ": store incomplete:")
		})
	case 91:
		return "output_missing", lastLine(lines, jobNote)
	case 92:
		return "not_refreshed", lastLine(lines, jobNote)
	case 93:
		return "environment", lastLine(lines, jobNote)
	}
	if line := lastLine(lines, containsAny(oomMarks)); line != "" {
		return "out_of_memory", line
	}
	if run.ExitCode == -1 || run.ExitCode == 137 || run.ExitCode == 247 ||
		lastLine(lines, containsAny(oomKillMarks)) != "" {
		// Killed by SIGKILL (mm_job itself, or a child: 137 from bash, -9
		// from Python as 247): in a container with a memory limit that is
		// almost always the OOM killer.
		return "out_of_memory", ""
	}
	if line := lastLine(lines, qualityAbort); line != "" {
		return "quality_gate", line
	}
	if line := lastLine(lines, containsAny(sourceMarks)); line != "" {
		return "source_unavailable", line
	}
	return "unknown", lastLine(lines, ownLine)
}

func lastLine(lines []string, match func(string) bool) string {
	for i := len(lines) - 1; i >= 0; i-- {
		if line := strings.TrimSpace(lines[i]); line != "" && match(line) {
			if len(line) > 300 {
				line = strings.ToValidUTF8(line[:300], "") + "…"
			}
			return line
		}
	}
	return ""
}

// qualityAbort is a quality gate that stopped the run; gates print a line
// when they pass too.
func qualityAbort(line string) bool {
	return strings.Contains(line, "质量闸门") && strings.Contains(line, "中止")
}

func containsAny(marks []string) func(string) bool {
	return func(line string) bool {
		for _, m := range marks {
			if strings.Contains(line, m) {
				return true
			}
		}
		return false
	}
}

// serviceNote is a line the service wrote, other than the generic exit note.
func serviceNote(line string) bool {
	return strings.HasPrefix(line, "[market-monitor] ") && !strings.HasPrefix(line, "[market-monitor] job exited") &&
		!strings.HasPrefix(line, "[market-monitor] attempt ")
}

func jobNote(line string) bool {
	return strings.HasPrefix(line, "[mm_job] ") && !strings.Contains(line, "pipeline exited")
}

// ownLine is a line the job's own code wrote, not a runner note or a marker.
func ownLine(line string) bool {
	return !strings.HasPrefix(line, "[mm_job]") && !strings.HasPrefix(line, "[market-monitor]") &&
		!strings.HasPrefix(line, "##") && !strings.HasPrefix(line, "== ")
}

// adminRunView adds what the log says: progress while a run is active, the
// reason once it failed.
func (s *server) adminRunView(run Run) AdminRun {
	view := adminRunOf(run)
	active := run.Status == "running"
	failed := run.Status == "failed" || run.Status == "interrupted"
	if !active && !failed {
		return view
	}
	tail, _, err := readLogTail(filepath.Join(s.runner.dataDir, "runs", run.ID+".log"), progressTailBytes)
	if err != nil {
		tail = ""
	}
	if active {
		view.Progress = progressOf(tail)
	} else {
		view.Reason, view.ReasonDetail = failureReason(run, tail)
	}
	return view
}

package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"
)

func TestProgressTakesTheLastMarker(t *testing.T) {
	log := "== 开始\n##progress 100/4393\n写入 1,000 行\n##progress 1200/4393\n"
	p := progressOf(log)
	if p == nil || p.Done != 1200 || p.Total != 4393 || p.WaitingUntil != "" {
		t.Fatalf("progress = %+v", p)
	}
}

func TestProgressShowsAWaitUntilTheNextCount(t *testing.T) {
	waiting := "##progress 800/4393\n##waiting 1764212400\n"
	p := progressOf(waiting)
	if p == nil || p.Done != 800 || p.WaitingUntil != time.Unix(1764212400, 0).UTC().Format(time.RFC3339) {
		t.Fatalf("waiting = %+v", p)
	}
	// Counting again ends the wait.
	if p := progressOf(waiting + "##progress 900/4393\n"); p.WaitingUntil != "" || p.Done != 900 {
		t.Fatalf("after the wait = %+v", p)
	}
}

func TestProgressIgnoresMalformedMarkers(t *testing.T) {
	for _, log := range []string{"", "no markers\n", "##progress 5/0\n", "##progress 9/4\n", "##progress x/4\n", "  ##progress 1/4\n"} {
		if p := progressOf(log); p != nil {
			t.Errorf("%q gave %+v", log, p)
		}
	}
}

func TestTypicalSecondsIsTheMedianOfRecentSuccesses(t *testing.T) {
	at := func(min int) string {
		return time.Date(2026, 11, 20, 0, min, 0, 0, time.UTC).Format(time.RFC3339)
	}
	run := func(status string, minutes int) Run {
		return Run{Job: "sentiment", Status: status, StartedAt: at(0), FinishedAt: at(minutes)}
	}
	// Newest first, as the index keeps them; the failed run and the sixth
	// success are not counted.
	runs := []Run{run("succeeded", 10), run("failed", 1), run("succeeded", 12), run("succeeded", 30),
		run("succeeded", 11), run("succeeded", 9), run("succeeded", 50)}
	if got := typicalSeconds(runs); got != 11*60 {
		t.Fatalf("typical = %d", got)
	}
	if got := typicalSeconds([]Run{run("failed", 3)}); got != 0 {
		t.Fatalf("no successes = %d", got)
	}
}

func TestFailureReasons(t *testing.T) {
	cases := []struct {
		name   string
		run    Run
		log    string
		reason string
		detail string
	}{
		{"timeout", Run{Error: "timeout", ExitCode: -1}, "  1200/4393\n[market-monitor] timeout after 6h0m0s\n", "timeout", ""},
		{"interrupted", Run{Error: "interrupted"}, "", "interrupted", ""},
		{"store", Run{Error: "exit_status", ExitCode: 94},
			"[mm_job] quant: store incomplete: 2026-11-26 has bars for 1196 stocks against 5144 on recent days (23%); the night's update did not finish\n[market-monitor] job exited: exit status 94\n",
			"store_incomplete", "[mm_job] quant: store incomplete: 2026-11-26 has bars for 1196 stocks against 5144 on recent days (23%); the night's update did not finish"},
		{"oom in a child", Run{Error: "exit_status", ExitCode: 1},
			"[3/5] 逐日横截面统计 ...\n\n\n面板重建失败：sentiment_build.py 被信号 9 终止（多半是内存超限被 OOM 杀掉）\n[mm_job] sentiment: pipeline exited 1\n\n[market-monitor] job exited: exit status 1\n",
			"out_of_memory", "面板重建失败：sentiment_build.py 被信号 9 终止（多半是内存超限被 OOM 杀掉）"},
		{"killed job", Run{Error: "exit_status", ExitCode: -1}, "[market-monitor] job exited: signal: killed\n", "out_of_memory", ""},
		{"quality gate", Run{Error: "exit_status", ExitCode: 1},
			"质量闸门 A 中止：基准日行情覆盖 2879 只 < 前一日 3723 只的 98%，疑似抓数残缺\n[09:42:46] 失败，退出码 1\n[mm_job] margin: pipeline exited 1\n",
			"quality_gate", "质量闸门 A 中止：基准日行情覆盖 2879 只 < 前一日 3723 只的 98%，疑似抓数残缺"},
		{"oom in marketdata", Run{Error: "exit_status", ExitCode: 137},
			"写入 1,000 行\n== update 退出码 137\n[mm_job] marketdata: pipeline exited 137\n", "out_of_memory", ""},
		{"oom in a py job", Run{Error: "exit_status", ExitCode: 247},
			"[2/5] 计算 ...\n[mm_job] panorama: pipeline exited -9\n", "out_of_memory", ""},
		{"gate passed, later step failed", Run{Error: "exit_status", ExitCode: 1},
			"质量闸门 A 通过：覆盖 5136 只\n质量闸门 B 通过\nTraceback (most recent call last):\nOSError: disk full\n[mm_job] margin: pipeline exited 1\n",
			"unknown", "OSError: disk full"},
		{"source warning recovered, check failed", Run{Error: "exit_status", ExitCode: 2},
			"⏸ 数据源不可用，5s 后重试（第 1 次）\n⚠ 连续 30 只失败，判定为源端故障（已处理 40/4393）\n▶ 数据源已恢复\n结论：不通过\n== check 退出码 2\n",
			"unknown", "结论：不通过"},
		{"source aborted at the start", Run{Error: "exit_status", ExitCode: 1},
			"数据源不可用（connection reset），本次更新已中止；库里数据未改动。\n稍后重试：python3 market_data.py update\n",
			"source_unavailable", "数据源不可用（connection reset），本次更新已中止；库里数据未改动。"},
		{"source", Run{Error: "exit_status", ExitCode: 2},
			"⚠ 连续 30 只失败，判定为源端故障（已处理 40/4393）\n⚠ 数据源没有恢复、或剩余时间不够再等一轮，提前收工，剩下的交给下一个补跑时段\n== check 退出码 2\n",
			"source_unavailable", "⚠ 数据源没有恢复、或剩余时间不够再等一轮，提前收工，剩下的交给下一个补跑时段"},
		{"output invalid", Run{Error: "output_invalid"}, "[market-monitor] outputs: history size\n", "output_invalid", "[market-monitor] outputs: history size"},
		{"service", Run{Error: "start_failed", ExitCode: -1}, "[market-monitor] start: fork/exec: no such file\n", "service_error", "[market-monitor] start: fork/exec: no such file"},
		{"unknown", Run{Error: "exit_status", ExitCode: 1},
			"Traceback (most recent call last):\n  File \"x.py\", line 3\nKeyError: 'close'\n[mm_job] etf: pipeline exited 1\n\n[market-monitor] job exited: exit status 1\n",
			"unknown", "KeyError: 'close'"},
	}
	for _, c := range cases {
		c.run.Status = "failed"
		reason, detail := failureReason(c.run, c.log)
		if reason != c.reason || detail != c.detail {
			t.Errorf("%s: got %q %q, want %q %q", c.name, reason, detail, c.reason, c.detail)
		}
	}
	if reason, _ := failureReason(Run{Status: "succeeded"}, "质量闸门 A 中止"); reason != "" {
		t.Fatalf("a success has a reason: %q", reason)
	}
}

func TestAdminRunsCarryProgressAndReasons(t *testing.T) {
	e := newTestEnv(t)
	r := e.srv.runner
	r.mu.Lock()
	r.runs = append([]Run{
		{ID: "run-live", Job: "margin", Status: "running", QueuedAt: "2026-11-27T01:49:05Z", StartedAt: "2026-11-27T01:49:05Z"},
		{ID: "run-oom", Job: "margin", Status: "failed", Error: "exit_status", ExitCode: 1,
			QueuedAt: "2026-11-27T04:15:58Z", StartedAt: "2026-11-27T04:16:00Z", FinishedAt: "2026-11-27T04:17:00Z"},
		{ID: "run-ok", Job: "margin", Status: "succeeded",
			QueuedAt: "2026-11-26T16:40:08Z", StartedAt: "2026-11-26T16:40:08Z", FinishedAt: "2026-11-26T16:52:08Z"},
	}, r.runs...)
	r.mu.Unlock()
	dir := filepath.Join(r.dataDir, "runs")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	for id, text := range map[string]string{
		"run-live": "##progress 1200/4393\n",
		"run-oom":  "面板重建失败：sentiment_build.py 被信号 9 终止（多半是内存超限被 OOM 杀掉）\n",
	} {
		if err := os.WriteFile(filepath.Join(dir, id+".log"), []byte(text), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	rec := e.call(t, "GET", "/v1/admin/runs", "", "admin")
	var out struct {
		Runs []AdminRun `json:"runs"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
		t.Fatal(err)
	}
	byID := map[string]AdminRun{}
	for _, run := range out.Runs {
		byID[run.ID] = run
	}
	if p := byID["run-live"].Progress; p == nil || p.Done != 1200 || p.Total != 4393 {
		t.Fatalf("live progress = %+v", p)
	}
	oom := byID["run-oom"]
	if oom.Reason != "out_of_memory" || !strings.Contains(oom.ReasonDetail, "被信号 9") || oom.Progress != nil {
		t.Fatalf("failed run = %+v", oom)
	}
	if ok := byID["run-ok"]; ok.Reason != "" || ok.Progress != nil {
		t.Fatalf("succeeded run = %+v", ok)
	}

	rec = e.call(t, "GET", "/v1/admin/jobs", "", "admin")
	var jobs struct {
		Jobs []jobView `json:"jobs"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &jobs); err != nil {
		t.Fatal(err)
	}
	if len(jobs.Jobs) != 1 {
		t.Fatalf("jobs = %+v", jobs.Jobs)
	}
	j := jobs.Jobs[0]
	if j.TypicalSeconds != 12*60 || j.LastRun == nil || j.LastRun.Progress == nil || j.LastRun.Progress.Done != 1200 {
		t.Fatalf("job = %+v %+v", j, j.LastRun)
	}
}

func TestEveryFailureReasonHasWordsInEveryLocale(t *testing.T) {
	for _, loc := range []string{"en-US", "zh-CN", "zh-TW"} {
		raw, err := os.ReadFile(filepath.Join("..", "frontend", "locales", loc+".json"))
		if err != nil {
			t.Fatal(err)
		}
		var copy map[string]any
		if err := json.Unmarshal(raw, &copy); err != nil {
			t.Fatal(err)
		}
		for _, r := range failureReasons {
			if s, _ := copy["reason_"+r].(string); s == "" {
				t.Errorf("%s has no reason_%s", loc, r)
			}
		}
	}
}

func TestFailureReasonsReturnsOnlyListedReasons(t *testing.T) {
	logs := []string{"", "质量闸门 x", "被信号 9", "数据源没有恢复", "[mm_job] store incomplete: x"}
	errs := []string{"exit_status", "timeout", "interrupted", "output_invalid", "start_failed", "log_unavailable"}
	for _, e := range errs {
		for _, code := range []int{-1, 0, 1, 2, 91, 92, 93, 94} {
			for _, log := range logs {
				r, _ := failureReason(Run{Status: "failed", Error: e, ExitCode: code}, log)
				if !slices.Contains(failureReasons, r) {
					t.Fatalf("%s/%d/%q gave unlisted %q", e, code, log, r)
				}
			}
		}
	}
}

func TestOnlyTheNewestRunsAreGivenReasons(t *testing.T) {
	e := newTestEnv(t)
	r := e.srv.runner
	r.mu.Lock()
	for i := 0; i < reasonedRuns+1; i++ {
		r.runs = append(r.runs, Run{ID: fmt.Sprintf("old-%03d", i), Job: "margin", Status: "failed",
			Error: "timeout", QueuedAt: "2026-11-01T00:00:00Z"})
	}
	r.mu.Unlock()
	rec := e.call(t, "GET", "/v1/admin/runs", "", "admin")
	var out struct {
		Runs []AdminRun `json:"runs"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
		t.Fatal(err)
	}
	if first, last := out.Runs[0], out.Runs[len(out.Runs)-1]; first.Reason != "timeout" || last.Reason != "" || last.Error != "timeout" {
		t.Fatalf("first %+v, last %+v", first, last)
	}
}

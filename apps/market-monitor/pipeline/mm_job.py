#!/usr/bin/env python3
"""Job entry for the market-monitor backend: ``mm_job.py <job>``.

The Go service runs this once per job with MM_DATA_DIR (the app's /data) and
MM_OUTPUT_DIR (a fresh staging directory). It

1. syncs the pipeline code from the image into a writable work directory
   (MM_DATA_DIR/work), which the pipeline treats as its install prefix and
   HOME, exactly as its own install.sh does; data already there is kept;
2. clears locks a killed run may have left, starts the pipeline's local data
   server when the job needs it, and runs the pipeline's own script for the
   job, unchanged;
3. converts the output that this run wrote into snapshot documents in
   MM_OUTPUT_DIR, which the service validates and installs.

The pipeline scripts hard-code /opt/daily-tasks; the image links that path to
the work directory (checked before every run), and the work directory's venv/
links to the interpreter running this file.

Exit codes: the pipeline's own non-zero code, passed through; 2 usage; and,
kept clear of the pipeline's own small codes, 91 output missing, 92 output
not written by this run, 93 environment (prefix link, data server).

One /data must have one runner: stale-lock clearing assumes no other process
(another container, or a hand-run pipeline script) writes the same work dir.
"""
import filecmp
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import time

SNAPSHOT_FORMAT = "market-monitor.snapshot/1"
EXIT_OUTPUT_MISSING = 91
EXIT_NOT_REFRESHED = 92
EXIT_ENVIRONMENT = 93
HERE = os.path.dirname(os.path.abspath(__file__))
PREFIX_LINK = "/opt/daily-tasks"

# job -> (working directory relative to the work dir, command, module, needs the data server)
JOBS = {
    "marketdata": ("MarketData", ["bash", "update.sh"], None, True),
    "sentiment": ("workspace", ["{py}", "analysis/sentiment_daily.py"], "sentiment", False),
    "panorama": ("workspace/panorama", ["bash", "daily_update.sh"], "panorama", True),
    "etf": ("workspace/analysis/panel", ["bash", "refresh.sh"], "etf", False),
    "margin": ("margin_scan", ["bash", "update.sh"], "margin", False),
}
RISK_INPUTS = ("margin", "sentiment", "etf")

OUTPUTS = {
    "margin": "margin_scan/out/payload.json",
    "sentiment": "workspace/analysis/out/sentiment/monitor.json",
    "etf": "workspace/analysis/panel/data/metrics.json",
    "panorama": "workspace/panorama/data/site_payload.json",
}

# Jobs run one at a time, so any of these present when a job starts was left
# by a run that was killed before its own cleanup ran.
STALE_LOCKS = ("margin_scan/.update.lock", "MarketData/.update.lock", "MarketData/.mdwrite.lock")

# The pipeline's data server (stock_server), started on loopback for the jobs
# that need it. Its upstream needs network egress from the platform. Panorama
# hard-codes port 8091, so production uses the default; MM_STOCK_SERVER_PORT
# exists for tests.
SERVER_CMD = ["{py}", "stock_mcp_integrated.py"]
SERVER_WAIT = 60

# Copies of the snapshots this entry published. Risk cites one of these only
# once the service has installed it, so it never cites a failed run's output
# or a snapshot the service refused.
PUBLISHED = ".mm-published"

# Top-level entries of the source that are not pipeline code.
NOT_COPIED = {"tests", "mm_job.py", "__pycache__"}


def prepare_work(src, work):
    """Copy the pipeline code into the work directory, never deleting files
    there, and point work/venv at the running interpreter's prefix."""
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        if rel == ".":
            dirs[:] = [d for d in dirs if d not in NOT_COPIED]
            files = [f for f in files if f not in NOT_COPIED]
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        target = os.path.normpath(os.path.join(work, rel))
        os.makedirs(target, exist_ok=True)
        for name in files:
            s, t = os.path.join(root, name), os.path.join(target, name)
            if not os.path.exists(t) or not filecmp.cmp(s, t, shallow=False):
                shutil.copy2(s, t)
    venv = os.path.join(work, "venv")
    if os.path.islink(venv) and os.path.realpath(venv) != os.path.realpath(sys.prefix):
        os.remove(venv)
    elif os.path.isdir(venv) and not os.path.islink(venv):
        os.rename(venv, venv + ".replaced-%d" % int(time.time()))
    if not os.path.lexists(venv):
        os.symlink(sys.prefix, venv)


def clear_stale_locks(work):
    for rel in STALE_LOCKS:
        path = os.path.join(work, rel)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
            print(f"[mm_job] cleared stale lock {rel}", flush=True)
        elif os.path.lexists(path):
            os.remove(path)
            print(f"[mm_job] cleared stale lock {rel}", flush=True)


def job_env(work):
    env = dict(os.environ)
    env["STOCK_SERVER_URL"] = "http://127.0.0.1:%d/mcp" % server_port()
    env.update({
        "HOME": work, "APP_HOME": work,
        "MD_HOME": os.path.join(work, "MarketData"),
        "WS_ROOT": os.path.join(work, "workspace"),
        "PY": sys.executable,
        "PATH": os.path.dirname(sys.executable) + os.pathsep + env.get("PATH", "/usr/bin:/bin"),
        "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
    })
    return env


def server_port():
    return int(os.environ.get("MM_STOCK_SERVER_PORT", "8091"))


def port_open(port):
    try:
        socket.create_connection(("127.0.0.1", port), 1).close()
        return True
    except OSError:
        return False


def start_server(work, env):
    """Start the data server on loopback and wait until it accepts; return
    the process, or None if the port was taken or it never listened. Its
    output goes to stock_server/server.log, not the job log."""
    port = server_port()
    if port_open(port):
        print(f"[mm_job] port {port} is already in use", file=sys.stderr)
        return None
    server_env = dict(env, MCP_HOST="127.0.0.1", MCP_PORT=str(port), MCP_TRANSPORT="http")
    command = [part.format(py=sys.executable) for part in SERVER_CMD]
    server_dir = os.path.join(work, "stock_server")
    with open(os.path.join(server_dir, "server.log"), "wb") as log:
        proc = subprocess.Popen(command, cwd=server_dir, env=server_env,
                                stdout=log, stderr=subprocess.STDOUT)
    deadline = time.time() + SERVER_WAIT
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        if port_open(port):
            return proc
        time.sleep(0.2)
    stop_server(proc)
    return None


def stop_server(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def clean(value):
    """Replace NaN and infinities, which JSON cannot carry, with null."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def snapshot(module, as_of, summary, rows=(), details=None):
    doc = {"format": SNAPSHOT_FORMAT, "module": module, "as_of": str(as_of)[:10],
           "summary": summary, "rows": list(rows)}
    if details:
        doc["details"] = details
    return doc


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def convert_margin(p):
    fields, cols = p["fields"], p["rows"]
    rows = [{f: cols[f][i] for f in fields} for i in range(len(cols[fields[0]]))]
    summary = {"meta": p["meta"], "overview": p["overview"], "hist_dates": p["hist_dates"]}
    codes = {r["code"] for r in rows}
    details = {code: series for code, series in p.get("hist", {}).items() if code in codes}
    return snapshot("margin", p["meta"]["as_of"], summary, rows, details)


def convert_sentiment(m):
    return snapshot("sentiment", m["asof"], m)


def convert_etf(m):
    summary = {k: v for k, v in m.items() if k != "funds"}
    return snapshot("etf", m["asof"], summary, m.get("funds", []))


def convert_panorama(p):
    rows = [dict(s, code=s["symbol"]) for s in p["stocks"]]
    summary = {k: v for k, v in p.items() if k not in ("stocks", "pct")}
    return snapshot("panorama", p["meta"]["asof"], summary, rows)


CONVERTERS = {"margin": convert_margin, "sentiment": convert_sentiment,
              "etf": convert_etf, "panorama": convert_panorama}


def last(values):
    return values[-1] if values else None


def risk_part(module, doc):
    s = doc["summary"]
    if module == "margin":
        o = s.get("overview") or {}
        return {
            "as_of": doc["as_of"],
            "lever_ratio": last((o.get("lever_series") or {}).get("ratio") or []),
            "lever_series": o.get("lever_series"),
            "guarantee": o.get("guarantee"),
            "guarantee_series": o.get("guarantee_series"),
            **{k: o.get(k) for k in ("n_res2", "n_critical", "n_high", "n_pledge_near", "n_pledge_breach",
                                     "n_unlock60", "n_cb_arb", "n_block", "n_gdhs_dump")},
        }
    if module == "sentiment":
        dims = {d.get("k"): d.get("v") for d in s.get("dims") or []}
        traj = s.get("traj") or {}
        return {
            "as_of": doc["as_of"], "headline": s.get("headline"), "breadth": dims.get("广度"), "dims": dims,
            "breadth_series": {"dates": traj.get("dates") or [], "values": (traj.get("series") or {}).get("广度") or []},
        }
    series = s.get("series") or {}
    return {
        "as_of": doc["as_of"], "current": s.get("current"),
        "health": {k: (s.get("health") or {}).get(k) for k in ("label", "light")},
        "nf_series": {"dates": (series.get("dates") or [])[-250:], "nf": (series.get("nf") or [])[-250:]},
    }


def build_risk(work, current):
    """Market-level readings from the margin, sentiment and ETF snapshots:
    the one this run is publishing (``current``) and the others only if the
    service has installed them. Each part carries its own as_of; the document
    is dated by the newest, i.e. it is "the latest readings known on that
    date"."""
    store = os.path.join(os.path.dirname(work), "snapshots")
    summary, inputs = {}, {}
    for module in RISK_INPUTS:
        doc = load_json(os.path.join(work, PUBLISHED, module + ".json"))
        if doc is None:
            continue
        if module != current and not os.path.exists(
                os.path.join(store, module, str(doc.get("as_of")) + ".json")):
            continue
        try:
            summary[module] = risk_part(module, doc)
            inputs[module] = doc["as_of"]
        except (KeyError, TypeError, AttributeError) as e:
            print(f"[mm_job] risk: skipping {module}: {e!r}", file=sys.stderr)
    if not inputs:
        return None
    summary["inputs"] = inputs
    return snapshot("risk", max(inputs.values()), summary)


def write_json(path, doc):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    os.replace(tmp, path)


def publish(job, work, out_dir, exit_code=0, started=None):
    """Write the job's snapshots. A failed job, or one whose output is
    missing or older than ``started`` (the run start), writes nothing."""
    if exit_code != 0:
        return exit_code
    module = JOBS[job][2]
    if module is None:
        return 0
    path = os.path.join(work, OUTPUTS[module])
    if not os.path.exists(path):
        print(f"[mm_job] {job}: output {OUTPUTS[module]} not found", file=sys.stderr)
        return EXIT_OUTPUT_MISSING
    if started is not None and os.path.getmtime(path) < started:
        print(f"[mm_job] {job}: {OUTPUTS[module]} was not written by this run", file=sys.stderr)
        return EXIT_NOT_REFRESHED
    doc = clean(CONVERTERS[module](load_json(path)))
    write_json(os.path.join(out_dir, module + ".json"), doc)
    os.makedirs(os.path.join(work, PUBLISHED), exist_ok=True)
    write_json(os.path.join(work, PUBLISHED, module + ".json"), doc)
    if module in RISK_INPUTS:
        try:
            risk = build_risk(work, module)
            if risk:
                write_json(os.path.join(out_dir, "risk.json"), clean(risk))
        except Exception as e:  # risk is derived; never fail the job for it
            print(f"[mm_job] risk not published: {e!r}", file=sys.stderr)
    return 0


def run(job, src, data_dir, out_dir, prefix_link=PREFIX_LINK):
    work = os.path.join(data_dir, "work")
    os.makedirs(work, exist_ok=True)
    if os.path.realpath(prefix_link) != os.path.realpath(work):
        print(f"[mm_job] {prefix_link} must link to {work}", file=sys.stderr)
        return EXIT_ENVIRONMENT
    prepare_work(src, work)
    clear_stale_locks(work)
    cwd, command, _, needs_server = JOBS[job]
    command = [part.format(py=sys.executable) for part in command]
    env = job_env(work)
    server = None
    if needs_server:
        server = start_server(work, env)
        if server is None:
            print(f"[mm_job] {job}: data server did not start on port {server_port()}", file=sys.stderr)
            return EXIT_ENVIRONMENT
    started = time.time() - 1  # filesystem timestamps may be coarse
    try:
        print(f"[mm_job] {job}: {' '.join(command)} in {cwd}", flush=True)
        code = subprocess.call(command, cwd=os.path.join(work, cwd), env=env)
    finally:
        if server is not None:
            stop_server(server)
    if code != 0:
        print(f"[mm_job] {job}: pipeline exited {code}", file=sys.stderr)
    return publish(job, work, out_dir, code, started)


def main(argv):
    if len(argv) != 2 or argv[1] not in JOBS:
        print("usage: mm_job.py {" + "|".join(sorted(JOBS)) + "}", file=sys.stderr)
        return 2
    return run(argv[1], HERE, os.environ.get("MM_DATA_DIR", "/data"), os.environ["MM_OUTPUT_DIR"])


if __name__ == "__main__":
    sys.exit(main(sys.argv))

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
   MM_OUTPUT_DIR, plus a curated parquet history file per row-based module
   (docs/store-v2.md), which the service validates and installs.

The pipeline scripts hard-code /opt/daily-tasks; the image links that path to
the work directory (checked before every run). They take their interpreter
from $PY, which is the one running this file.

The platform checkpoints the data directory before an update and refuses any
symlink, socket, fifo or multiply-linked file in it, so this entry creates
none there and removes the ones an earlier version or the pipeline left.

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
import stat
import subprocess
import sys
import time

SNAPSHOT_FORMAT = "market-monitor.snapshot/1"
HISTORY_FORMAT = "market-monitor.history/1"
EXIT_OUTPUT_MISSING = 91
EXIT_NOT_REFRESHED = 92
EXIT_ENVIRONMENT = 93
HERE = os.path.dirname(os.path.abspath(__file__))
PREFIX_LINK = "/opt/daily-tasks"
SITE_DIR = os.path.join(HERE, "pysite")

# job -> (working directory relative to the work dir, command, module, needs the data server)
JOBS = {
    "marketdata": ("MarketData", ["bash", "update.sh"], None, True),
    "sentiment": ("workspace", ["{py}", "analysis/sentiment_daily.py"], "sentiment", False),
    "panorama": ("workspace/panorama", ["bash", "daily_update.sh"], "panorama", True),
    "etf": ("workspace/analysis/panel", ["bash", "refresh.sh"], "etf", False),
    "margin": ("margin_scan", ["bash", "update.sh"], "margin", False),
}
RISK_INPUTS = ("margin", "sentiment", "etf")

# History file columns per module (market-monitor.history/1), in file order.
# Types are explicit: "s" is a string column, "d" a double column. A schema
# change is a new format version, never an edit of this table.
_STR, _DBL = "s", "d"
HISTORY_COLUMNS = {
    "margin": (
        [("code", _STR), ("name", _STR)]
        + [(c, _DBL) for c in ("price", "chg", "rz", "ratio", "dratio20", "rz_chg5", "rz_chg20",
                               "buf_call", "buf_liq", "pnl", "score", "frag")]
        + [("state", _STR), ("level", _STR), ("tags", _STR)]
    ),
    "panorama": (
        [("code", _STR), ("name", _STR), ("sw1", _STR)]
        + [(c, _DBL) for c in ("price", "mktcap", "pe", "pb", "roe", "upside")]
        + [("label", _STR), ("quad", _STR), ("profile", _STR)]
        + [(c, _DBL) for c in ("s_value", "s_growth", "s_cyclical", "s_dividend", "s_momentum", "s_quality")]
    ),
    "etf": [("code", _STR), ("name", _STR), ("cat", _STR), ("cum_ytd", _DBL), ("cum20", _DBL)],
}
HISTORY_SUFFIX = ".history.parquet"

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
NOT_COPIED = {"tests", "mm_job.py", "pysite", "__pycache__"}


def prepare_work(src, work):
    """Copy the pipeline code into the work directory, never deleting files
    there, and leave nothing in it that the platform's data checkpoint
    refuses."""
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
    remove_venv_link(work)
    unshare_hard_links(work)


def remove_venv_link(work):
    """Up to 0.1.0-beta.5, work/venv linked to the interpreter, and a real
    directory found there was renamed to venv.replaced-<time>. Nothing runs
    from either (jobs use $PY), and a venv holds symlinks, so remove them."""
    for name in os.listdir(work):
        if name != "venv" and not name.startswith("venv.replaced-"):
            continue
        path = os.path.join(work, name)
        if os.path.islink(path) or not os.path.isdir(path):
            os.remove(path)
        else:
            shutil.rmtree(path)
        print(f"[mm_job] removed work/{name}", flush=True)


UNSHARE_SUFFIX = ".mm-unshare"


def unshare_hard_links(work):
    """Give every regular file under work that has more than one link its own
    copy, keeping its mtime. The pipeline's write-ahead snapshots used to
    hard-link partitions (MD_SNAPSHOT_COPY now makes them copy); this clears
    the ones left. Raises OSError if a copy fails, leaving no partial copy."""
    n = 0
    for root, dirs, files in os.walk(work):
        for name in files:
            path = os.path.join(root, name)
            if name.endswith(UNSHARE_SUFFIX):
                os.remove(path)  # a partial copy from an interrupted run
                continue
            st = os.lstat(path)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink < 2:
                continue
            tmp = path + UNSHARE_SUFFIX
            try:
                shutil.copy2(path, tmp)
                os.replace(tmp, path)
            except OSError:
                if os.path.lexists(tmp):
                    os.remove(tmp)
                raise
            n += 1
    if n:
        print(f"[mm_job] gave {n} hard-linked file(s) their own copy", flush=True)


def report_unsafe(data_dir):
    """Name what is left under data_dir that the platform's data checkpoint
    refuses (a symlink, socket, fifo or device), so an update that fails on
    it can be traced. Nothing this app writes is one of those."""
    for root, dirs, files in os.walk(data_dir):
        for name in dirs + files:
            path = os.path.join(root, name)
            mode = os.lstat(path).st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                print(f"[mm_job] warning: {os.path.relpath(path, data_dir)} is not a regular file "
                      "or directory; the platform cannot checkpoint this data", file=sys.stderr)


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
    # The pipeline's own HTML pages are not used (the app has its own
    # frontend) and need vendored JS the app does not ship.
    env["MM_NO_HTML"] = "1"
    # Copy write-ahead snapshots: a hard link is a second link to the file,
    # which the platform's data checkpoint refuses.
    env["MD_SNAPSHOT_COPY"] = "1"
    # Arrow's default allocator keeps freed memory: reading the bar store's
    # partitions one after another left sentiment's panel build near 1.6 GB
    # (0.8 GB with the system allocator) under the container's 2 GiB.
    env["ARROW_DEFAULT_MEMORY_POOL"] = "system"
    # Trading days follow Beijing time; the scripts use local dates.
    env.setdefault("TZ", "Asia/Shanghai")
    env.update({
        "HOME": work, "APP_HOME": work,
        "MD_HOME": os.path.join(work, "MarketData"),
        "WS_ROOT": os.path.join(work, "workspace"),
        "PY": sys.executable,
        # pysite/sitecustomize.py sends plain-HTTP requests to remote hosts over
        # https: only HTTPS_PROXY is set, so plain HTTP would not be proxied.
        "PYTHONPATH": os.pathsep.join(p for p in (SITE_DIR, env.get("PYTHONPATH", "")) if p),
        "PATH": os.path.dirname(sys.executable) + os.pathsep + env.get("PATH", "/usr/bin:/bin"),
        "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
    })
    return env


# Before a job's first request, wait until the platform's egress proxy lets a
# reviewed host through: right after the service starts (a bootstrap run) the
# forwarder answers 403 until its broker session is up. The probe host is the
# quotes API, which every installation reviews. A proxy that never opens does
# not stop the job; its own requests then fail and say why.
PROXY_WAIT = 120
PROXY_POLL = 2.0
PROXY_PROBE = os.environ.get("MM_PROXY_PROBE", "quotes.internal.anchan.kazuhahub.com:443")


def proxy_connect_ok(proxy_url, target, timeout=5):
    """One CONNECT through proxy_url to target (host:port); True on a 2xx."""
    from urllib.parse import urlsplit
    p = urlsplit(proxy_url if "://" in proxy_url else "http://" + proxy_url)
    try:
        with socket.create_connection((p.hostname, p.port or 80), timeout) as sock:
            head = "CONNECT %s HTTP/1.1\r\nHost: %s\r\n" % (target, target)
            if p.username:
                import base64
                cred = "%s:%s" % (p.username, p.password or "")
                head += "Proxy-Authorization: Basic %s\r\n" % base64.b64encode(cred.encode()).decode()
            sock.sendall((head + "\r\n").encode())
            line = sock.makefile("rb").readline(256).decode("latin-1").split()
            return len(line) >= 2 and line[1].startswith("2")
    except (OSError, ValueError):
        return False


def wait_for_proxy(env, wait=None, poll=None):
    """Wait until the egress proxy passes a CONNECT to a reviewed host. Returns
    True when it does (or no proxy is configured), False after the wait."""
    proxy_url = env.get("HTTPS_PROXY") or env.get("https_proxy")
    if not proxy_url:
        return True
    wait = PROXY_WAIT if wait is None else wait
    poll = PROXY_POLL if poll is None else poll
    deadline = time.time() + wait
    tries = 0
    while True:
        tries += 1
        if proxy_connect_ok(proxy_url, PROXY_PROBE):
            if tries > 1:
                print(f"[mm_job] egress proxy ready after {tries} tries", flush=True)
            return True
        if time.time() >= deadline:
            print(f"[mm_job] egress proxy still refuses {PROXY_PROBE} after {wait}s; running anyway",
                  file=sys.stderr, flush=True)
            return False
        time.sleep(poll)


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


RATIO_HIST_WIDTH = 0.5
RATIO_HIST_BINS = 30


def ratio_hist(rows, median=None):
    """Distribution of the margin crowding ratio (percent), for the overview
    chart: rows are paged by the service, so the bins must come from here.
    Bin i covers [i*width, (i+1)*width); the last bin is open-ended. Rows
    without a ratio, or with a negative one (bad data), are skipped. None when
    no row has one."""
    values = []
    for r in rows:
        x = r.get("ratio")
        if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x >= 0:
            values.append(x)
    if not values:
        return None
    counts = [0] * RATIO_HIST_BINS
    for x in values:
        # Clamp before int(): a huge finite ratio divides to inf.
        counts[RATIO_HIST_BINS - 1 if x >= RATIO_HIST_BINS * RATIO_HIST_WIDTH else int(x // RATIO_HIST_WIDTH)] += 1
    values.sort()
    mid = len(values) // 2
    computed = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2
    if not isinstance(median, (int, float)) or isinstance(median, bool) or not math.isfinite(median):
        median = computed
    return {"width": RATIO_HIST_WIDTH, "counts": counts, "median": median}


def convert_margin(p):
    fields, cols = p["fields"], p["rows"]
    rows = [{f: cols[f][i] for f in fields} for i in range(len(cols[fields[0]]))]
    overview = dict(p["overview"])
    if "ratio_hist" not in overview:
        hist = ratio_hist(rows, overview.get("ratio_med"))
        if hist:
            overview["ratio_hist"] = hist
    summary = {"meta": p["meta"], "overview": overview, "hist_dates": p["hist_dates"]}
    codes = {r["code"] for r in rows}
    details = {code: series for code, series in p.get("hist", {}).items() if code in codes}
    return snapshot("margin", p["meta"]["as_of"], summary, rows, details)


def convert_sentiment(m):
    return snapshot("sentiment", m["asof"], m)


def convert_etf(m):
    summary = {k: v for k, v in m.items() if k != "funds"}
    return snapshot("etf", m["asof"], summary, m.get("funds", []))


# Panorama's export step writes the industry breakdown, market medians and
# the change against the previous run into its own page data (site/data.js),
# not into site_payload.json. They are added to the summary when that file
# was written by this run for the same date; otherwise the snapshot is
# published without them.
PANORAMA_SITE = "workspace/panorama/site/data.js"
PANORAMA_SITE_PREFIX = "window.PANORAMA="
PANORAMA_SITE_META = ("corr", "inter", "n_industries")
PANORAMA_MARKET = ("median_pe", "median_pb", "above_ma120_pct")


def load_panorama_site(work, started):
    path = os.path.join(work, PANORAMA_SITE)
    try:
        if started is not None and os.path.getmtime(path) < started:
            raise ValueError("not written by this run")
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
        if not text.startswith(PANORAMA_SITE_PREFIX) or not text.endswith(";"):
            raise ValueError("unexpected format")
        site = json.loads(text[len(PANORAMA_SITE_PREFIX):-1])
        if not isinstance(site, dict):
            raise ValueError("not an object")
        return site
    except (OSError, ValueError) as e:
        print(f"[mm_job] panorama: page data not used: {e}", file=sys.stderr)
        return None


def convert_panorama(p, site=None):
    rows = [dict(s, code=s["symbol"]) for s in p["stocks"]]
    summary = {k: v for k, v in p.items() if k not in ("stocks", "pct")}
    site_meta = (site or {}).get("meta") or {}
    asof = p["meta"]["asof"]
    if site and site_meta.get("asof") == asof:
        if isinstance(site.get("industries"), list):
            summary["industries"] = site["industries"]
        if isinstance(site.get("market"), dict):
            summary["market"] = {k: site["market"][k] for k in PANORAMA_MARKET if k in site["market"]}
        # diff.py compares the latest two snapshot dates, not the run date: a
        # backfill of an older date would otherwise carry a later comparison.
        diff = site.get("diff")
        if isinstance(diff, dict) and diff.get("cur") == asof:
            summary["diff"] = diff
        summary["meta"] = {**summary["meta"],
                           **{k: site_meta[k] for k in PANORAMA_SITE_META if k in site_meta}}
    elif site:
        print("[mm_job] panorama: page data is for another date, not used", file=sys.stderr)
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
    service has installed them (as ``<as_of>.json.gz``). Each part carries its own as_of; the document
    is dated by the newest, i.e. it is "the latest readings known on that
    date"."""
    store = os.path.join(os.path.dirname(work), "snapshots")
    summary, inputs = {}, {}
    for module in RISK_INPUTS:
        doc = load_json(os.path.join(work, PUBLISHED, module + ".json"))
        if doc is None:
            continue
        if module != current and not os.path.exists(
                os.path.join(store, module, str(doc.get("as_of")) + ".json.gz")):
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


def history_cast(kind, value):
    """One cell of a history column: a number (int or float, never a bool) or
    a string as the column type requires, otherwise None."""
    if kind == _STR:
        return value if isinstance(value, str) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def history_schema(module):
    import pyarrow as pa
    columns = [pa.field(name, pa.string() if kind == _STR else pa.float64())
               for name, kind in HISTORY_COLUMNS[module]]
    return pa.schema(columns)


def history_table(module, doc):
    """The module's history table from a snapshot document (after ``clean``),
    and the number of values nulled per column. A missing or null value is
    not counted; only a value of the wrong type (a bool in a numeric column,
    a number in a string column, a non-finite number) is."""
    import pyarrow as pa
    schema = history_schema(module)
    nulled = {name: 0 for name, _ in HISTORY_COLUMNS[module]}
    arrays = []
    for (name, kind), field in zip(HISTORY_COLUMNS[module], schema):
        values = []
        for row in doc["rows"]:
            raw = row.get(name)
            value = history_cast(kind, raw)
            if value is None and raw is not None:
                nulled[name] += 1
            values.append(value)
        arrays.append(pa.array(values, type=field.type))
    table = pa.Table.from_arrays(arrays, schema=schema)
    metadata = {"format": HISTORY_FORMAT, "module": module, "as_of": doc["as_of"]}
    return table.replace_schema_metadata(metadata), nulled


def write_history(module, doc, path):
    """Write ``<module>.history.parquet`` atomically (zstd, one row group per
    1M rows) and log how many odd values became null."""
    import pyarrow.parquet as pq
    table, nulled = history_table(module, doc)
    tmp = path + ".tmp"
    try:
        pq.write_table(table, tmp, compression="zstd")
        os.replace(tmp, path)
    except BaseException:
        # Never leave a half-written file behind: the service refuses any
        # unexpected name in the output directory.
        if os.path.lexists(tmp):
            os.remove(tmp)
        raise
    odd = ", ".join(f"{k}={v}" for k, v in nulled.items() if v) or "none"
    print(f"[mm_job] {module}: history {len(doc['rows'])} rows, values nulled: {odd}", flush=True)


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
    if module == "panorama":
        doc = clean(convert_panorama(load_json(path), load_panorama_site(work, started)))
    else:
        doc = clean(CONVERTERS[module](load_json(path)))
    write_json(os.path.join(out_dir, module + ".json"), doc)
    if module in HISTORY_COLUMNS:
        # A history file is mandatory for these modules. If it cannot be
        # written the service finds it missing and refuses the whole run.
        try:
            write_history(module, doc, os.path.join(out_dir, module + HISTORY_SUFFIX))
        except Exception as e:
            print(f"[mm_job] {module}: history not written: {e!r}", file=sys.stderr)
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
    report_unsafe(data_dir)
    clear_stale_locks(work)
    cwd, command, _, needs_server = JOBS[job]
    command = [part.format(py=sys.executable) for part in command]
    env = job_env(work)
    wait_for_proxy(env)
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
        try:
            unshare_hard_links(work)
        except OSError as e:  # the next run's prepare_work retries, and fails loudly
            print(f"[mm_job] could not unshare hard links: {e!r}", file=sys.stderr)
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

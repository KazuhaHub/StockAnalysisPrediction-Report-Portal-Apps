# market-monitor backend image: the Go service, the Python pipeline and its
# virtual environment. Build from the repository root:
#   docker build --platform linux/amd64 -f apps/kazuha-hub-market-monitor/service/Dockerfile .
#
# The platform runs it as 65532:65532 with a read-only root filesystem, no
# network (egress goes through the in-process forwarder to the broker, which
# answers only for hosts an administrator has reviewed), a 16 MiB /tmp and the
# installation's data mounted at /data. The pipeline hard-codes /opt/daily-tasks,
# which is linked to /data/work.
#
# linux/amd64 only: py-mini-racer (an akshare dependency) publishes Linux
# wheels for x86_64 only; build with --platform linux/amd64. Base images are
# pinned by digest so every build starts from the same bases (the images are
# still not bit-identical: pip timestamps and the jsonpath sdist build vary).

FROM golang:1.26.11-bookworm@sha256:dc40a13b61304647ed7e5d581d246b86413dfc29d63c6d018310feb93cd98fc0 AS service
WORKDIR /src/apps/kazuha-hub-market-monitor/service
COPY packages/extensionprotocol /src/packages/extensionprotocol
COPY packages/proxy /src/packages/proxy
COPY apps/kazuha-hub-market-monitor/service/go.mod apps/kazuha-hub-market-monitor/service/go.sum ./
# The first third-party modules of the service (the parquet reader and its
# dependencies). Downloaded in their own layer, keyed by go.mod and go.sum, so
# a source change does not download them again; go.sum pins every hash.
RUN go mod download
COPY apps/kazuha-hub-market-monitor/service/*.go ./
RUN rm -f *_test.go && CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o /out/market-monitor .

FROM python:3.11-slim-bookworm@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39 AS venv
COPY apps/kazuha-hub-market-monitor/pipeline/requirements.lock /tmp/requirements.lock
# Byte-compile at build time: the root filesystem is read-only at run time,
# so nothing could cache compiled modules there later.
RUN python -m venv /app/venv \
 && /app/venv/bin/pip install --no-cache-dir -r /tmp/requirements.lock \
 && rm -rf /app/venv/lib/python3.11/site-packages/pip /app/venv/lib/python3.11/site-packages/setuptools \
 && /app/venv/bin/python -m compileall -q -j 0 /app/venv/lib/python3.11/site-packages

FROM python:3.11-slim-bookworm@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39
ENV PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=Asia/Shanghai \
    MM_PYTHON=/app/venv/bin/python \
    MM_JOB_ENTRY=/app/pipeline/mm_job.py \
    MM_DATA_DIR=/data
COPY --from=venv /app/venv /app/venv
COPY --from=service /out/market-monitor /app/market-monitor
# .dockerignore keeps tests, install/systemd files and caches out of this copy.
COPY apps/kazuha-hub-market-monitor/pipeline /app/pipeline
RUN chmod -R a+rX /app/pipeline \
 && ln -s /data/work /opt/daily-tasks
USER 65532:65532
ENTRYPOINT ["/app/market-monitor"]

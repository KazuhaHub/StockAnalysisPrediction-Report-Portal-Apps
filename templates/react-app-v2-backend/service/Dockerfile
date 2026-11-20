# APP_ID backend image. Build from the repository root:
#   docker build --platform linux/amd64 -f apps/APP_ID/service/Dockerfile -t APP_ID:dev .
#
# The platform runs it as 65532:65532 with a read-only root filesystem, no
# network, a 16 MiB /tmp and the installation's data mounted at /data. The image
# therefore holds one static binary and nothing writable: /data and the two
# socket directories exist only so the runner's bind mounts have a mount point.
# CA certificates are included for the optional forward proxy (network.proxy),
# which tunnels TLS that the service terminates itself.
#
# The base image is pinned by digest so every build starts from the same base.

FROM golang:1.26.11-bookworm@sha256:dc40a13b61304647ed7e5d581d246b86413dfc29d63c6d018310feb93cd98fc0 AS build
WORKDIR /src/apps/APP_ID/service
COPY packages/extensionprotocol /src/packages/extensionprotocol
COPY packages/proxy /src/packages/proxy
COPY apps/APP_ID/service/go.mod ./
COPY apps/APP_ID/service/*.go ./
RUN rm -f *_test.go \
 && CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o /out/app . \
 && mkdir -p /out/data /out/run/portal-app/http /out/run/portal-app/broker

FROM scratch
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=build --chown=65532:65532 /out/data /data
COPY --from=build --chown=65532:65532 /out/run /run
COPY --from=build /out/app /app
USER 65532:65532
ENTRYPOINT ["/app"]

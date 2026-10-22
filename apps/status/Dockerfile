FROM golang:1.26.10-bookworm AS build
WORKDIR /src
COPY apps/status/service/go.mod apps/status/service/go.sum ./
RUN go mod download
COPY apps/status/service/ ./
ARG APP_VERSION=0.1.0-dev
RUN CGO_ENABLED=0 go build -trimpath -ldflags "-s -w -X main.version=${APP_VERSION}" -o /out/status ./cmd/status

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/status /status
WORKDIR /data
EXPOSE 8791
USER 65532:65532
ENTRYPOINT ["/status"]
CMD ["serve", "-listen", ":8791", "-database", "/data/status.db", "-storage-key-file", "/run/secrets/status-storage.key", "-pairing-file", "/run/secrets/status-pairing.json"]

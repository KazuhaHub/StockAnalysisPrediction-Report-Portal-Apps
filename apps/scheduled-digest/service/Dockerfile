FROM golang:1.26.10-bookworm AS build
WORKDIR /src
COPY apps/scheduled-digest/service/go.mod ./
COPY apps/scheduled-digest/service/ ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o /out/scheduled-digest ./...

FROM scratch
COPY --from=build /out/scheduled-digest /scheduled-digest
USER 65532:65532
ENTRYPOINT ["/scheduled-digest"]

# Multi-stage: build → distroless static
FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY cmd ./cmd
COPY internal ./internal
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /out/proxy ./cmd

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/proxy /proxy
EXPOSE 8000
USER nonroot:nonroot
ENTRYPOINT ["/proxy"]

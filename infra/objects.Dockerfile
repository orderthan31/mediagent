# Official MinIO source security release, not an unverified binary mirror.
FROM golang:1.26-bookworm@sha256:a688600ca24f8a4d3ca77f95b0dd40704a9fc787c826660eb7ba0b641b8b175d AS build
ARG MINIO_COMMIT=9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a
ENV GOMAXPROCS=2 GOFLAGS=-p=2 GOMEMLIMIT=1536MiB CGO_ENABLED=0
WORKDIR /src
RUN git init && git remote add origin https://github.com/minio/minio.git \
    && git fetch --depth=1 origin ${MINIO_COMMIT} && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "$MINIO_COMMIT" \
    && go build -trimpath -ldflags='-s -w' -o /minio .
FROM debian:bookworm-slim@sha256:3783cc01769c7b2b1b83a5c5ad96c815348e28ed7da68e2e3687004faa906251
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* && useradd --uid 10001 --create-home media \
    && mkdir /data && chown 10001:10001 /data
COPY --from=build /minio /usr/local/bin/minio
COPY --from=build /src/LICENSE /usr/share/doc/minio/LICENSE
COPY infra/objects-entrypoint.sh /usr/local/bin/objects-entrypoint
RUN chmod 755 /usr/local/bin/objects-entrypoint
LABEL org.opencontainers.image.source="https://github.com/minio/minio" \
      org.opencontainers.image.revision="9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a" \
      org.opencontainers.image.licenses="AGPL-3.0"
USER 10001:10001
ENTRYPOINT ["/usr/local/bin/objects-entrypoint"]

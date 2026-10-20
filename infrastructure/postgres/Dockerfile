# PostgreSQL 16 (Alpine) with the pgvector extension compiled in (ADR 0010).
#
# Why our own image: this project's existing data volume was created by postgres:16-alpine
# (musl). The official pgvector/pgvector image is Debian-based (glibc); swapping the base OS
# changes text collation, so existing text indexes would need REINDEX or a dump/restore.
# Compiling pgvector into the SAME Alpine base keeps the volume, collation and indexes valid.
#
# Pinned version: upgrade deliberately (edit PGVECTOR_VERSION, rebuild, run the smoke checks in
# docs/rag-runbook.md). No compiler or git remains in the runtime image.

ARG POSTGRES_IMAGE=postgres:16-alpine
ARG PGVECTOR_VERSION=v0.8.7

FROM ${POSTGRES_IMAGE} AS builder
ARG PGVECTOR_VERSION
# with_llvm=no skips PostgreSQL's optional LLVM bitcode step (.bc files), which is only a JIT
# optimisation. It avoids needing clang in the build image; the generated vector.so is the same.
RUN apk add --no-cache --virtual .build-deps git make gcc musl-dev \
    && git clone --depth 1 --branch "${PGVECTOR_VERSION}" https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && make -C /tmp/pgvector with_llvm=no \
    && make -C /tmp/pgvector install with_llvm=no \
    && rm -rf /tmp/pgvector

FROM ${POSTGRES_IMAGE}
# Only the compiled extension is copied; the build dependencies stay in the builder stage.
COPY --from=builder /usr/local/lib/postgresql/vector.so /usr/local/lib/postgresql/vector.so
COPY --from=builder /usr/local/share/postgresql/extension/vector.control /usr/local/share/postgresql/extension/vector.control
COPY --from=builder /usr/local/share/postgresql/extension/vector--*.sql /usr/local/share/postgresql/extension/

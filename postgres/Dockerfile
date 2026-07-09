# Aexy Postgres image: stock postgres:18-alpine + pgvector extension.
#
# Why a custom image: keeping the alpine base preserves the postgres user UID
# and the libc collations the existing data volume was created with. A switch
# to the official pgvector/pgvector:pg18 image (Debian) would require a
# pg_dump/restore cycle to avoid UID and libc collation issues.
#
# pgvector v0.8.1 is the first tag with PostgreSQL 18 support — earlier tags
# fail to compile against the v18 headers.

FROM postgres:18-alpine

ARG PGVECTOR_VERSION=v0.8.1

# postgres:18-alpine is not digest-pinned, so its required bitcode compiler
# version (CLANG in pgxs/src/Makefile.global) drifts whenever the upstream
# image is rebuilt against a newer Alpine/LLVM. Detect it at build time
# instead of hardcoding a version number that will silently rot again.
RUN CLANG_VER=$(sed -n 's/^CLANG *= *clang-//p' /usr/local/lib/postgresql/pgxs/src/Makefile.global) \
 && apk add --no-cache --virtual .build-deps \
        build-base "clang${CLANG_VER}" "llvm${CLANG_VER}-dev" git \
 && cd /tmp \
 && git clone --depth 1 --branch ${PGVECTOR_VERSION} \
        https://github.com/pgvector/pgvector.git \
 && cd pgvector \
 && make OPTFLAGS="" \
 && make install \
 && cd / \
 && rm -rf /tmp/pgvector \
 && apk del .build-deps

COPY initdb/ /docker-entrypoint-initdb.d/

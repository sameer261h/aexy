# Aexy Postgres image: stock postgres:18-alpine + pgvector extension.
#
# Why a custom image: keeping the alpine base preserves the postgres user UID
# and the libc collations the existing data volume was created with. A switch
# to the official pgvector/pgvector:pg18 image (Debian) would require a
# pg_dump/restore cycle to avoid UID and libc collation issues.
#
# pgvector v0.8.1 is the first tag with PostgreSQL 18 support — earlier tags
# fail to compile against the v18 headers.

FROM postgres:18-alpine@sha256:9a8afca54e7861fd90fab5fdf4c42477a6b1cb7d293595148e674e0a3181de15

ARG PGVECTOR_VERSION=v0.8.1

RUN apk add --no-cache --virtual .build-deps \
        build-base clang19 llvm19-dev git \
 && cd /tmp \
 && git clone --depth 1 --branch ${PGVECTOR_VERSION} \
        https://github.com/pgvector/pgvector.git \
 && cd pgvector \
 && make OPTFLAGS="" \
 && make install \
 && cd / \
 && rm -rf /tmp/pgvector \
 && apk del .build-deps

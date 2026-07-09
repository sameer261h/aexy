-- Auto-run by the postgres entrypoint on first init of an empty data
-- directory (see /docker-entrypoint-initdb.d/ in the base image docs).
-- The Dockerfile compiles and installs the pgvector shared library, but
-- installing the library alone does not enable it in a database — without
-- this, the app's own table creation fails with:
--   sqlalchemy.exc.ProgrammingError: type "vector" does not exist
CREATE EXTENSION IF NOT EXISTS vector;

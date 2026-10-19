-- Postgres initialization script for multiple databases
-- Mounted into /docker-entrypoint-initdb.d/ in postgres container

SELECT 'CREATE DATABASE lemmy'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'lemmy')\gexec

GRANT ALL PRIVILEGES ON DATABASE lemmy TO incubrix;

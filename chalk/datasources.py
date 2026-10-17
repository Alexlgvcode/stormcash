"""The hosted Postgres (spec §6.1), configured in the Chalk dashboard as the
PostgreSQL integration `neon_stormcash`. Its credentials live in Chalk, never here."""

from chalk.sql import PostgreSQLSource

neon_stormcash = PostgreSQLSource(name="neon_stormcash")

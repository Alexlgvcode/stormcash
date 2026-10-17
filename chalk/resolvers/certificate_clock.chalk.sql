-- resolves: Certificate
-- source: neon_stormcash
-- type: online
-- count: one
-- Sets the default certificate.as_of to the sim clock (see merchant_clock.chalk.sql).
select cast(${certificate.id} as text) as id,
       coalesce(cast(extract(epoch from max(received_at)) as bigint),
                cast(extract(epoch from now()) as bigint)) as as_of
from uploads

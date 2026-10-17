-- resolves: Merchant
-- source: neon_stormcash
-- type: online
-- count: one
-- Sets the default merchant.as_of to the sim clock, the time of the server's latest sync (wall clock if none yet).
-- A query that passes merchant.as_of as an input skips this resolver.
select cast(${merchant.id} as text) as id,
       coalesce(cast(extract(epoch from max(received_at)) as bigint),
                cast(extract(epoch from now()) as bigint)) as as_of
from uploads

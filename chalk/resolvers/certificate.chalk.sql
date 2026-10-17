-- resolves: Certificate
-- source: neon_stormcash
-- type: online
-- count: one_or_none
-- A cert's status and its holder's home region.
select encode(s.cert_id, 'hex') as id, s.status, s.storm_mode,
       (select r.region_id from certificates c join residents r on r.resident_id = c.resident_id
        where c.cert_id = s.cert_id limit 1) as home_region
from cert_status s
where s.cert_id = decode(${certificate.id}, 'hex')

-- resolves: Certificate
-- source: neon_stormcash
-- type: online
-- count: one
-- cap_drain features (spec 13.2), same definitions as server/stormcash/detectors.py,
-- over the 15 minutes of simulated time ending at certificate.as_of (inclusive).
with win as (
    select cast(${certificate.as_of} as bigint) as t
),
me as (
    select cert_id, max_cap_cents, storm_mode_at from cert_status where cert_id = decode(${certificate.id}, 'hex')
),
spend as (
    select p.device_ts, p.merchant_id, t.amount_cents, m.region_id
    from payments p
    join tags t on t.tag_hash = p.tag_hash
    join merchants m on m.merchant_id = p.merchant_id
    where p.cert_id = (select cert_id from me)
      and p.device_ts between (select t from win) - 900 and (select t from win)
      and p.status in ('settled', 'held', 'denied_knowing')
),
cap as (
    select coalesce(
        (select c.cap_cents from certificates c
         where c.cert_id = (select cert_id from me) and c.issued_at <= (select t from win)
         order by c.cert_ver desc limit 1),
        (select max_cap_cents from me)) as cap_cents
),
home as (
    select (select r.region_id from certificates c join residents r on r.resident_id = c.resident_id
            where c.cert_id = (select cert_id from me) limit 1) as region_id
),
previous as (
    select max(p.device_ts) as ts from payments p
    where p.cert_id = (select cert_id from me)
      and p.device_ts < (select min(device_ts) from spend)
      and p.status in ('settled', 'held', 'denied_knowing')
)
select
    cap.cap_cents,
    coalesce((select sum(amount_cents) from spend), 0) as spent_15m_cents,
    (select count(distinct merchant_id) from spend) as distinct_merchants_15m,
    case when cap.cap_cents > 0
         then cast(round(cast(coalesce((select sum(amount_cents) from spend), 0) as numeric) / cap.cap_cents, 4)
                   as double precision) end as drain_share_15m,
    coalesce((select array_agg(distinct region_id order by region_id) from spend where region_id is not null),
             cast('{}' as text[])) as regions_15m,
    coalesce(home.region_id is not null
             and exists (select 1 from spend where region_id is not null and region_id <> home.region_id), false)
        as region_mismatch_15m,
    (select case when storm_mode_at is not null
                 then cast(round(cast((select t from win) - storm_mode_at as numeric) / 60, 1) as double precision) end
     from me) as minutes_since_storm_mode,
    case when previous.ts is not null
         then cast(round(cast((select min(device_ts) from spend) - previous.ts as numeric) / 60, 1)
                   as double precision) end as gap_since_last_activity_min,
    cast(mod(((select t from win) - 14400) / 3600, 24) as integer) as hour_of_day
from cap, home, previous

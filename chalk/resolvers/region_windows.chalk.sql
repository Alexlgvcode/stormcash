-- resolves: Region
-- source: neon_stormcash
-- type: online
-- count: one
-- region_dark features (spec 13.3) at region.as_of, same definitions as server/stormcash/detectors.py.
-- each cert's latest version unless frozen, a cert's region is its resident's, and with no upload yet the
-- dark stretch starts at the region's first cert. Also the replayed weather alerts active at as_of.
with win as (
    select cast(${region.as_of} as bigint) as now_s
),
reg as (
    select region_id from regions where region_id = ${region.id}
),
certs as (
    select distinct on (c.cert_id) c.cert_id, c.expires_at, c.issued_at
    from certificates c
    join residents r on r.resident_id = c.resident_id
    join cert_status s on s.cert_id = c.cert_id
    where r.region_id = (select region_id from reg) and s.status <> 'frozen'
    order by c.cert_id, c.cert_ver desc
),
active as (
    select expires_at from certs
    where expires_at > (select now_s from win) and issued_at <= (select now_s from win)
),
last_upload as (
    select cast(extract(epoch from max(received_at)) as bigint) as t from uploads
    where region_id = (select region_id from reg) and received_at <= to_timestamp((select now_s from win))
)
select
    (select count(*) from active) as active_certs,
    (select case when count(*) > 0
                 then cast(round(cast(count(*) filter (where expires_at < (select now_s from win) + 43200) as numeric)
                                 / count(*), 4) as double precision) end
     from active) as expiring_12h_share,
    cast(round(cast((select now_s from win) - coalesce(last_upload.t, (select min(issued_at) from certs)) as numeric)
               / 3600, 1) as double precision) as hours_since_last_upload,
    (select count(distinct p.merchant_id) from payments p join merchants m on m.merchant_id = p.merchant_id
     where m.region_id = (select region_id from reg)
       and p.device_ts >= (select now_s from win) - 21600 and p.device_ts < (select now_s from win))
        as merchants_open_6h,
    coalesce((select array_agg(a.event order by a.alert_id) from weather_alerts a
              where a.region_id = (select region_id from reg) and a.source = 'replayed'
                and (a.onset is null or a.onset <= (select now_s from win))
                and (a.expires is null or a.expires > (select now_s from win))),
             cast('{}' as text[])) as replayed_alert_events
from last_upload

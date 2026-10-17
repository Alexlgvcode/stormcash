-- resolves: Merchant
-- source: neon_stormcash
-- type: online
-- count: one
-- merchant_silence features (spec 13.1), same definitions as server/stormcash/detectors.py,
-- over the 6 h of simulated time ending at merchant.as_of. Neighbors are shops within
-- 3 grid cells; accepted payments are settled, held or denied_knowing.
with win as (
    select cast(${merchant.as_of} as bigint) - 21600 as ws, cast(${merchant.as_of} as bigint) as we
),
me as (
    select merchant_id, merchant_pub, x, y from merchants where merchant_id = decode(${merchant.id}, 'hex')
),
nearby as (
    select o.merchant_id, o.merchant_pub, o.merchant_id = me.merchant_id as is_me
    from merchants o, me
    where o.merchant_id = me.merchant_id
       or (me.x is not null and me.y is not null and o.x is not null and o.y is not null
           and sqrt(power(o.x - me.x, 2) + power(o.y - me.y, 2)) <= 3)
),
counts as (
    select n.merchant_id, n.is_me, count(distinct c.contact_id) / 6.0 as cph
    from nearby n
    left join contacts c on (c.device_pub = n.merchant_pub or c.peer_pub = n.merchant_pub)
        and c.ts >= (select ws from win) and c.ts < (select we from win)
    group by n.merchant_id, n.is_me
),
silence as (
    select (select cph from counts where is_me) as cph,
           (select count(*) from counts where not is_me) as neighbors,
           coalesce((select percentile_cont(0.5) within group (order by cph) from counts where not is_me), 0)
               as neighbor_median
),
pay as (
    select count(*) as accepted,
           count(*) filter (where p.funded_pool_cents > 0) as pool_count,
           coalesce(sum(p.funded_pool_cents), 0) as pool_cents,
           count(*) filter (where t.cum_cents >= 0.8 * s.max_cap_cents) as near_cap,
           count(distinct p.cert_id) filter (where exists (select 1 from cases k where k.cert_id = p.cert_id))
               as cheater_certs
    from payments p
    join tags t on t.tag_hash = p.tag_hash
    join cert_status s on s.cert_id = p.cert_id
    where p.merchant_id = (select merchant_id from me)
      and p.device_ts >= (select ws from win) and p.device_ts < (select we from win)
      and p.status in ('settled', 'held', 'denied_knowing')
),
mine as (
    select c.contact_id, bool_or(c.paired) as paired, bool_or(c.device_pub = me.merchant_pub) as logged_by_me
    from contacts c, me
    where (c.device_pub = me.merchant_pub or c.peer_pub = me.merchant_pub)
      and c.ts >= (select ws from win) and c.ts < (select we from win)
    group by c.contact_id
)
select
    cast(round(cast(silence.cph as numeric), 3) as double precision) as contacts_per_hour_6h,
    silence.neighbors as neighbors_6h,
    cast(round(cast(silence.neighbor_median as numeric), 3) as double precision) as neighbor_median_contacts_6h,
    cast(round(cast(silence.cph / greatest(silence.neighbor_median, 0.1) as numeric), 4) as double precision)
        as silence_ratio_6h,
    pay.accepted as accepted_count_6h,
    pay.pool_count as pool_funded_count_6h,
    pay.pool_cents as pool_funded_cents_6h,
    case when pay.accepted > 0
         then cast(round(cast(pay.pool_count as numeric) / pay.accepted, 4) as double precision) end
        as pool_funded_share_6h,
    pay.cheater_certs as distinct_cheater_certs_6h,
    case when pay.accepted > 0
         then cast(round(cast(pay.near_cap as numeric) / pay.accepted, 4) as double precision) end
        as near_cap_share_6h,
    (select case when count(*) filter (where logged_by_me) > 0
                 then cast(round(cast(count(*) filter (where logged_by_me and paired) as numeric)
                                 / count(*) filter (where logged_by_me), 4) as double precision) end
     from mine) as paired_contact_share_6h,
    (select count(*) from mine where not paired) as one_sided_contacts_6h,
    (select count(*) from candidates k, me
     where k.kind = 'merchant_silence' and k.subject_id = encode(me.merchant_id, 'hex')
       and k.window_start < (select ws from win)) as prior_windows_flagged
from silence, pay

-- resolves: Merchant
-- source: neon_stormcash
-- type: online
-- count: one_or_none
-- A shop's fixed attributes.
select encode(merchant_id, 'hex') as id, display_name as name, region_id, simulated
from merchants
where merchant_id = decode(${merchant.id}, 'hex')

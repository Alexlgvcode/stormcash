-- resolves: Region
-- source: neon_stormcash
-- type: online
-- count: one_or_none
-- A region's fixed attributes.
select region_id as id, display_name as name, county
from regions
where region_id = ${region.id}

-- Bounded, on-demand world survey. Never runs in the per-tick production monitor.
local M = {}

local function inside(position, area)
  return position.x >= area[1][1] and position.x < area[2][1]
     and position.y >= area[1][2] and position.y < area[2][2]
end

local function identity(e)
  return e.unit_number and tostring(e.unit_number) or e.name .. ":" .. e.position.x .. ":" .. e.position.y
end

local function reference(e)
  if not e or not e.valid then return nil end
  return {id = identity(e), prototype = e.name, entity_type = e.type, position = e.position,
          force_index = e.force.index, built = e.type ~= "entity-ghost"}
end

local function status_name(status)
  for name, value in pairs(defines.entity_status) do if status == value then return name end end
  return "unknown"
end

function M.capture(scope)
  local area = scope.area
  assert(area[2][1] - area[1][1] <= 128 and area[2][2] - area[1][2] <= 128, "Survey radius must be at most 64.")
  local surface = game.surfaces[scope.surface_index]
  local found = surface.find_entities_filtered{area = area, limit = 16385}
  assert(#found <= 16384, "Survey contains more than 16384 entities; use a smaller radius.")
  local resources, infrastructure, obstacles, water, ungenerated = {}, {}, {}, {}, {}
  for _, e in pairs(found) do
    local p = e.prototype
    if e.type == "resource" and inside(e.position, area) then
      local mining = p.mineable_properties
      resources[#resources + 1] = {id = identity(e), prototype = e.name, position = e.position,
        amount = e.amount, minable = e.minable and mining.minable,
        infinite = p.infinite_resource, required_fluid = mining.required_fluid,
        mining_time = mining.mining_time, products = mining.products or {},
        standable = surface.can_place_entity{name = "character", position = e.position, force = scope.force_index}}
    end
    -- All forces' collision obstacles matter to the player, including trees and cliffs.
    if e.type ~= "resource" and p.collision_mask.layers.player then
      obstacles[#obstacles + 1] = {id = identity(e), prototype = e.name, entity_type = e.type,
        position = e.position, bounding_box = e.bounding_box}
    end
    if e.force.index == scope.force_index and (e.type == "electric-pole" or e.type == "inserter"
      or e.type == "mining-drill" or e.type == "generator" or e.type == "solar-panel"
      or e.type == "accumulator" or e.type == "electric-energy-interface"
      or e.type == "transport-belt" or e.type == "underground-belt" or e.type == "splitter"
      or e.type == "container" or e.type == "logistic-container") then
      local record = reference(e)
      record.direction, record.status, record.active = e.direction, status_name(e.status), e.active
      record.electric_network_id, record.energy_j = e.electric_network_id, e.energy
      if e.type == "inserter" or e.type == "mining-drill" then
        record.drop_target, record.drop_position = reference(e.drop_target), e.drop_position
      end
      if e.type == "inserter" then
        record.pickup_target, record.pickup_position = reference(e.pickup_target), e.pickup_position
      elseif e.type == "electric-pole" then
        record.supply_radius = p.get_supply_area_distance(e.quality)
        record.max_wire_distance = p.get_max_wire_distance(e.quality)
        record.copper_neighbours = {}
        -- false is essential: inspecting wires must not allocate a connector.
        local connector = e.get_wire_connector(defines.wire_connector_id.pole_copper, false)
        for _, connection in pairs(connector and connector.connections or {}) do
          record.copper_neighbours[#record.copper_neighbours + 1] = reference(connection.target.owner)
        end
        table.sort(record.copper_neighbours, function(a,b) return a.id < b.id end)
      elseif e.type == "generator" or e.type == "solar-panel" or e.type == "electric-energy-interface" then
        record.prototype_max_generation_kw = p.get_max_energy_production(e.quality) * 60 / 1000
      end
      infrastructure[#infrastructure + 1] = record
    end
  end
  assert(#resources <= 8192 and #obstacles <= 4096 and #infrastructure <= 2048,
    "Survey exceeds resource/obstacle/infrastructure limits; use a smaller radius.")
  for _, tile in pairs(surface.find_tiles_filtered{area = area, collision_mask = "water_tile"}) do
    water[#water + 1] = {x = tile.position.x, y = tile.position.y}
  end
  for x = math.floor(area[1][1] / 32), math.ceil(area[2][1] / 32) - 1 do
    for y = math.floor(area[1][2] / 32), math.ceil(area[2][2] / 32) - 1 do
      if not surface.is_chunk_generated({x, y}) then ungenerated[#ungenerated + 1] = {x = x, y = y} end
    end
  end
  for _, list in ipairs({resources, infrastructure, obstacles}) do table.sort(list, function(a,b) return a.id < b.id end) end
  table.sort(water, function(a,b) return a.y == b.y and a.x < b.x or a.y < b.y end)
  return {schema_version = 1, tick = game.tick, area = area, resources = resources,
          infrastructure = infrastructure, obstacles = obstacles, water_tiles = water,
          ungenerated_chunks = ungenerated,
          limits = {resources = 8192, infrastructure = 2048, obstacles = 4096},
          note = "Direct observations only. Finite mineral amounts are stocks; infinite-resource amounts are not reserves. Standable checks local character placement, not a walking route. Copper edges include ghost wires; network IDs establish actual membership. Generator ratings are theoretical prototype limits, not available power."}
end

return M

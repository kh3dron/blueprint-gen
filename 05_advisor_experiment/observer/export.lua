-- Runtime observations only. No data-stage changes and no factory mutations.
local catalog = require("catalog")
local survey = require("survey")
local M = {}

local function keys(table_value)
  local out = {}
  for key in pairs(table_value or {}) do out[#out + 1] = key end
  table.sort(out)
  return out
end

local function contents(inventory)
  if not inventory or not inventory.valid then return {} end
  local out = inventory.get_contents()
  table.sort(out, function(a, b)
    return a.name .. ":" .. a.quality < b.name .. ":" .. b.quality
  end)
  return out
end

local function amounts(entries)
  local out = {}
  for _, entry in pairs(entries or {}) do
    out[#out + 1] = {name = entry.name, type = entry.type or "item", amount = entry.amount,
                    probability = entry.probability, amount_min = entry.amount_min,
                    amount_max = entry.amount_max}
  end
  table.sort(out, function(a, b) return a.name < b.name end)
  return out
end

local function status_name(status)
  for name, value in pairs(defines.entity_status) do
    if status == value then return name end
  end
  return "unknown"
end

function M.rules(force)
  local recipes, machines, technologies, items = {}, {}, {}, {}
  for _, name in ipairs(catalog.recipes) do
    local p = prototypes.recipe[name]
    assert(p, "Missing recipe prototype: " .. name)
    recipes[name] = {categories = p.categories, seconds = p.energy, enabled = p.enabled,
                    inputs = amounts(p.ingredients), outputs = amounts(p.products)}
  end
  for _, name in ipairs(catalog.machines) do
    local p = prototypes.entity[name]
    local speed = name == "lab" and p.get_researching_speed("normal") or p.get_crafting_speed("normal")
    machines[name] = {speed = speed, categories = keys(p.crafting_categories),
                     electric_kw = p.electric_energy_source_prototype and p.energy_usage * 60 / 1000 or 0,
                     fuel_kw = p.burner_prototype and p.energy_usage * 60 / 1000 / p.burner_prototype.effectivity or 0,
                     idle_kw = p.electric_energy_source_prototype and p.electric_energy_source_prototype.drain * 60 / 1000 or 0,
                     size = {p.tile_width, p.tile_height}}
  end
  for _, name in ipairs(catalog.technologies) do
    local t, p = force.technologies[name], prototypes.technology[name]
    local unlocks = {}
    for _, effect in pairs(p.effects) do
      if effect.type == "unlock-recipe" then unlocks[#unlocks + 1] = effect.recipe end
    end
    table.sort(unlocks)
    technologies[name] = {prerequisites = keys(p.prerequisites), trigger = p.research_trigger,
                         count = t.research_unit_count, seconds = t.research_unit_energy / 60,
                         packs = amounts(t.research_unit_ingredients), unlocks = unlocks,
                         count_formula = p.research_unit_count_formula}
  end
  for name, kind in pairs(catalog.items) do items[name] = kind end
  return {recipes = recipes, machines = machines, technologies = technologies, items = items,
          fuel_kj = {coal = prototypes.item.coal.fuel_value / 1000}}
end

function M.entities(scope)
  local surface = game.surfaces[scope.surface_index]
  local found = surface.find_entities_filtered{
    area = scope.area, force = scope.force_index,
    type = {"assembling-machine", "furnace", "lab", "entity-ghost"}}
  assert(#found <= 256, "Observer area contains more than 256 machines/ghosts; choose a smaller radius.")
  local out = {}
  for _, e in pairs(found) do
    local ghost = e.type == "entity-ghost"
    local name = ghost and e.ghost_name or e.name
    local kind = ghost and e.ghost_type or e.type
    if kind == "assembling-machine" or kind == "furnace" or kind == "lab" then
      local recipe, recipe_quality
      if kind ~= "lab" and not ghost then recipe, recipe_quality = e.get_recipe() end
      local record = {
        id = tostring(e.unit_number), prototype = name, entity_type = kind,
        built = not ghost, position = {x = e.position.x, y = e.position.y},
        direction = e.direction, quality = e.quality.name,
        recipe = recipe and recipe.name or nil,
        recipe_quality = recipe_quality and recipe_quality.name or nil,
        status = ghost and "ghost" or status_name(e.status),
        energy_j = not ghost and e.energy or 0,
        electric_network_id = not ghost and e.electric_network_id or nil,
        active = not ghost and e.active or false,
        modules = not ghost and contents(e.get_module_inventory()) or {},
        speed_bonus = not ghost and e.speed_bonus or 0,
        productivity_bonus = not ghost and e.productivity_bonus or 0,
      }
      if not ghost and kind ~= "lab" then
        record.products_finished = e.products_finished
        record.output_inventory = contents(e.get_output_inventory())
      end
      out[#out + 1] = record
    end
  end
  table.sort(out, function(a, b) return a.id < b.id end)
  return out
end

function M.signature(entities)
  local parts = {}
  for _, e in ipairs(entities) do
    -- Operating status and energy buffers fluctuate during normal crafting.
    -- Configuration, recipe and modifier changes invalidate the whole interval.
    parts[#parts + 1] = table.concat({e.id, e.prototype, tostring(e.built), e.recipe or "",
      e.recipe_quality or "", e.quality, tostring(e.active), e.position.x, e.position.y, e.direction,
      e.electric_network_id or "", e.speed_bonus or 0, e.productivity_bonus or 0,
      helpers.table_to_json(e.modules)}, "|")
  end
  return table.concat(parts, "\n")
end

function M.capture(player, scope, generation, observation, include_survey)
  local force = game.forces[scope.force_index]
  local inventory = player.get_main_inventory()
  local researched, progress, crafted = {}, {}, {}
  for _, name in ipairs(catalog.technologies) do
    if force.technologies[name].researched then researched[#researched + 1] = name end
  end
  if force.current_research then
    progress[force.current_research.name] = math.floor(force.research_progress * force.current_research.research_unit_count)
  end
  local statistics = force.get_item_production_statistics(scope.surface_index)
  for _, name in ipairs({"iron-plate", "copper-plate", "lab"}) do
    crafted[name] = statistics.get_input_count{name = name, quality = "normal"}
  end
  return {
    export_schema_version = 1,
    exporter = {name = "blueprint-gen-observer", version = script.active_mods["blueprint-gen-observer"]},
    factorio_version = script.active_mods.base, active_mods = script.active_mods,
    tick = game.tick, generation = generation, scope = scope,
    player = {index = player.index, name = player.name, position = player.position,
              inventory = contents(inventory), inventory_observed = inventory ~= nil and inventory.valid},
    researched = researched, research_units_completed = progress, crafted = crafted,
    machines = M.entities(scope), resolved_rules = M.rules(force),
    observation = observation,
    survey = include_survey and survey.capture(scope) or nil,
    unknowns = {"net input supply rates", "material routing connectivity", "available electric generation",
                "output capacity when not visibly blocked"},
  }
end

return M

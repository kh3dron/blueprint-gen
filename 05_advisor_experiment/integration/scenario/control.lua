-- Test fixture only: creates machines, finite inputs and test electricity in a
-- disposable map. Never included in the normal observer package.
script.on_init(function()
  local surface = game.surfaces[1]
  surface.request_to_generate_chunks({0, 0}, 2)
  surface.force_generate_chunk_requests()
  for _, e in pairs(surface.find_entities_filtered{area = {{-40, -40}, {40, 40}}, type = {"tree", "simple-entity"}}) do e.destroy() end
  local tiles = {}
  for x = -40, 40 do for y = -40, 40 do tiles[#tiles + 1] = {name = "grass-1", position = {x, y}} end end
  surface.set_tiles(tiles)
  local force = game.forces.player
  storage.surface, storage.force = surface.index, force.index
  for _, tech in ipairs({"steam-power", "electronics", "automation-science-pack", "automation"}) do force.technologies[tech].researched = true end
  local function assembler(recipe, x, y, ingredients)
    local e = surface.create_entity{name = "assembling-machine-1", position = {x, y}, force = force}
    e.set_recipe(recipe)
    for name, count in pairs(ingredients) do e.insert{name = name, count = count} end
    return e
  end
  storage.red1 = assembler("automation-science-pack", 0, 0, {["copper-plate"] = 30, ["iron-gear-wheel"] = 30})
  storage.red2 = assembler("automation-science-pack", 0, 6, {["copper-plate"] = 30, ["iron-gear-wheel"] = 30})
  storage.cable = assembler("copper-cable", 6, 0, {["copper-plate"] = 200})
  storage.gears = assembler("iron-gear-wheel", 12, 0, {["iron-plate"] = 200})
  surface.create_entity{name = "lab", position = {12, 6}, force = force}
  local power = surface.create_entity{name = "electric-energy-interface", position = {0, -4}, force = force}
  power.electric_buffer_size = 1000000000
  power.power_production = 10000000
  power.energy = 1000000000
  surface.create_entity{name = "substation", position = {6, 3}, force = force}
end)

script.on_event(defines.events.on_tick, function(event)
  if event.tick == 30 then
    remote.call("blueprint-gen-observer", "start_area", storage.surface, storage.force, 0, -8, 32, 60)
  elseif event.tick == 3631 then
    local stats = {
      red1_finished = storage.red1.products_finished, red2_finished = storage.red2.products_finished,
      cable_finished = storage.cable.products_finished, cable_contents = storage.cable.get_output_inventory().get_contents(),
      gears_finished = storage.gears.products_finished,
    }
    helpers.write_file("observer-smoke-results.json", helpers.table_to_json(stats), false)
  elseif event.tick == 3650 then
    remote.call("blueprint-gen-observer", "start_area", storage.surface, storage.force, 0, -8, 32, 2)
  elseif event.tick == 3710 then
    storage.red1.set_recipe("iron-gear-wheel")
  end
end)

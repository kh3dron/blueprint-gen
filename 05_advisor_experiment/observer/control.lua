local export = require("export")
local window = require("window")
local catalog = require("catalog")
local routing = require("routing")

local function init()
  storage.generation = (storage.generation or 0) + 1
  storage.windows = {}
  storage.route_requests = {}
end
script.on_init(init)
script.on_configuration_changed(init)

local function scope_for(player, radius)
  radius = radius or 32
  assert(radius >= 1 and radius <= 128 and radius == math.floor(radius), "Radius must be an integer from 1 to 128.")
  return {player_index = player.index, force_index = player.force.index, force_name = player.force.name,
          surface_index = player.surface.index, surface_name = player.surface.name,
          map_seed = player.surface.map_gen_settings.seed,
          area = {{player.position.x - radius, player.position.y - radius},
                  {player.position.x + radius, player.position.y + radius}}}
end

local function viewer(scope)
  if scope.player_index ~= 0 then return game.get_player(scope.player_index) end
  local surface, force = game.surfaces[scope.surface_index], game.forces[scope.force_index]
  if not surface or not force then return nil end
  return {index = 0, name = "headless", connected = false, surface = surface, force = force,
          position = {x = (scope.area[1][1] + scope.area[2][1]) / 2, y = (scope.area[1][2] + scope.area[2][2]) / 2},
          get_main_inventory = function() return nil end, print = function(message) log(message) end}
end

local function write(player, scope, observation, include_survey)
  local capture = export.capture(player, scope, storage.generation, observation, include_survey)
  local path = "blueprint-gen-observer/player-" .. player.index .. "-tick-" .. game.tick .. (include_survey and "-survey" or "") .. ".json"
  local recipient
  if player.index ~= 0 then recipient = player.connected and player.index or 0 end
  helpers.write_file(path, helpers.table_to_json(capture), false, recipient)
  player.print("Advisor observation written to script-output/" .. path)
  return path
end

local function start_scope(scope, seconds)
  local player = assert(viewer(scope), "Player/scope not found")
  seconds = seconds or 60
  assert(seconds >= 1 and seconds <= 600 and seconds == math.floor(seconds), "Seconds must be an integer from 1 to 600.")
  local entities = export.entities(scope)
  local products = {}
  for _, recipe in ipairs(catalog.recipes) do
    local out, deterministic = {}, true
    for _, product in pairs(prototypes.recipe[recipe].products) do
      if not product.amount or (product.probability and product.probability ~= 1) then deterministic = false end
      out[product.name] = product.amount
    end
    if deterministic then products[recipe] = out end
  end
  storage.windows[scope.player_index] = {scope = scope, end_tick = game.tick + seconds * 60,
    state = window.start(game.tick, entities, export.signature(entities), storage.generation), products = products}
  player.print("Advisor is measuring this fixed area for " .. seconds .. " simulated seconds.")
end

local function start(player_index, seconds, radius)
  local player = assert(game.get_player(player_index), "Player not found")
  start_scope(scope_for(player, radius), seconds)
end

script.on_event(defines.events.on_tick, function()
  routing.tick(storage.generation)
  for player_index, measurement in pairs(storage.windows) do
    local player = viewer(measurement.scope)
    if not player or player.surface.index ~= measurement.scope.surface_index or player.force.index ~= measurement.scope.force_index then
      storage.windows[player_index] = nil
    else
      local ok, err = pcall(function()
        local entities = export.entities(measurement.scope)
        -- A scenario can start a window earlier in this same tick.
        if game.tick > measurement.state.last_tick then
          window.advance(measurement.state, game.tick, entities, export.signature(entities), storage.generation, measurement.products)
        end
        if game.tick >= measurement.end_tick then
          write(player, measurement.scope, window.finish(measurement.state))
          storage.windows[player_index] = nil
        end
      end)
      if not ok then
        player.print("Advisor observation stopped: " .. tostring(err))
        storage.windows[player_index] = nil
      end
    end
  end
end)

script.on_event(defines.events.on_script_path_request_finished, function(event)
  routing.finished(event,storage.generation)
end)

-- Conservative invalidation. Any of these edits, even outside the observed area,
-- invalidate a running interval. Ordinary crafting/status changes do not.
for _, event in ipairs({defines.events.on_built_entity, defines.events.on_robot_built_entity,
  defines.events.on_player_mined_entity, defines.events.on_robot_mined_entity, defines.events.on_entity_died,
  defines.events.on_player_rotated_entity, defines.events.on_entity_settings_pasted, defines.events.on_gui_closed,
  defines.events.on_research_finished, defines.events.on_research_reversed,
  defines.events.on_player_built_tile, defines.events.on_player_mined_tile,
  defines.events.on_robot_built_tile, defines.events.on_robot_mined_tile,
  defines.events.script_raised_built, defines.events.script_raised_destroy,
  defines.events.script_raised_revive, defines.events.script_raised_teleported, defines.events.script_raised_set_tiles}) do
  script.on_event(event, function() storage.generation = storage.generation + 1 end)
end

local function command(handler)
  return function(cmd)
    local player = cmd.player_index and game.get_player(cmd.player_index)
    if not player then game.print("Run this command as a player."); return end
    local ok, err = pcall(handler, player, cmd.parameter)
    if not ok then player.print("Advisor observer: " .. tostring(err)) end
  end
end

local function radius_parameter(parameter)
  if not parameter or parameter == "" then return nil end
  return assert(tonumber(parameter), "Radius must be a number.")
end

commands.add_command("advisor-export", "Export the nearby machines. Optional radius (default 32).",
  command(function(player, parameter) write(player, scope_for(player, radius_parameter(parameter))) end))
commands.add_command("advisor-observe", "Observe 60 seconds of machine production. Optional radius (default 32).",
  command(function(player, parameter) start(player.index, 60, radius_parameter(parameter)) end))
commands.add_command("advisor-survey", "Survey resources, water, obstacles and direct connections. Optional radius (default 32, max 64).",
  command(function(player, parameter) write(player, scope_for(player, radius_parameter(parameter)), nil, true) end))
commands.add_command("advisor-route", "Find a walking approach to one mineral tile: X Y COUNT.",
  command(function(player,parameter)
    local fields={}
    for field in string.gmatch(parameter or "","%S+") do fields[#fields+1]=field end
    assert(#fields==3,"Usage: /advisor-route X Y COUNT (use resource coordinates from the survey).")
    local quantity=assert(tonumber(fields[3]),"Quantity must be a number.")
    routing.start(player.character,tonumber(fields[1]),tonumber(fields[2]),quantity,storage.generation)
  end))

-- Read-only integration hooks for isolated scenario tests and future frontends.
remote.add_interface("blueprint-gen-observer", {
  route_character = function(actor,x,y,count)
    return routing.start(actor,x,y,count,storage.generation)
  end,
  start = start,
  start_area = function(surface_index, force_index, x, y, radius, seconds)
    local actor = {index = 0, position = {x = x, y = y}, surface = game.surfaces[surface_index], force = game.forces[force_index]}
    start_scope(scope_for(actor, radius), seconds)
  end,
  survey_area = function(surface_index, force_index, x, y, radius)
    local actor = {index = 0, position = {x = x, y = y}, surface = game.surfaces[surface_index], force = game.forces[force_index]}
    local scope = scope_for(actor, radius)
    return write(viewer(scope), scope, nil, true)
  end,
  capture = function(player_index, radius)
    local player = assert(game.get_player(player_index), "Player not found")
    return write(player, scope_for(player, radius))
  end,
})

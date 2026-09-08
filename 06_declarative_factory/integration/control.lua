-- Test-only application of compiled plans. This is not a live-world apply command.
local ground=require("ground")
local designs=require("designs")
script.on_event(defines.events.on_chunk_generated,ground.chunk_generated)

local function config_of(entity)
  local d={name=entity.name,position=entity.position,direction=entity.direction}
  if entity.type=="assembling-machine" then local r=entity.get_recipe(); if r then d.recipe=r.name end end
  return d
end
local function equal(a,b)
  return a.name==b.name and a.direction==b.direction and a.recipe==b.recipe
    and a.position.x==b.position.x and a.position.y==b.position.y
end
local function preflight(change)
  if change.kind~="additive" then return false,"blocked design" end
  local surface,force=game.surfaces.nauvis,game.forces.player
  for _,key in ipairs(change.retained) do
    local entity=storage.managed[key]
    if not entity or not entity.valid or not equal(config_of(entity),designs.first.entities[key]) then return false,"drift" end
  end
  for key,e in pairs(change.add) do
    if not storage.managed[key] then
      if force.recipes[e.name] and not force.recipes[e.name].enabled then return false,"locked entity" end
      if e.recipe and not force.recipes[e.recipe].enabled then return false,"locked recipe" end
      if not surface.can_place_entity{name=e.name,position=e.position,direction=e.direction,force=force,
        build_check_type=defines.build_check_type.manual,forced=false} then return false,"collision" end
    elseif not storage.managed[key].valid or not equal(config_of(storage.managed[key]),e) then return false,"drift" end
  end
  return true
end
local function apply(change)
  assert(#change.wire_add==0,"this engine fixture does not apply wire migrations")
  local ok,reason=preflight(change)
  assert(ok,reason)
  local count=0
  for key,e in pairs(change.add) do
    if not storage.managed[key] then
      local entity=assert(game.surfaces.nauvis.create_entity{name=e.name,position=e.position,direction=e.direction,force="player"})
      if e.recipe then entity.set_recipe(e.recipe) end
      assert(equal(config_of(entity),e),"engine changed requested configuration")
      storage.managed[key]=entity
      count=count+1
    end
  end
  return count
end
local function observe(manifest)
  local observed={source="factorio-proving-ground",manifest_sha256=manifest.sha256,tick=game.tick,
    factorio_version=script.active_mods.base,active_mods=script.active_mods,entities={}}
  for key in pairs(manifest.entities) do
    local entity=storage.managed[key]
    if entity and entity.valid then
      observed.entities[key]={unit_number=entity.unit_number,configuration=config_of(entity)}
    end
  end
  return observed
end

script.on_init(function()
  ground.init()
  storage.managed={}
end)
script.on_event(defines.events.on_tick,function(event)
  if event.tick==10 then
    local ok,reason=preflight(designs.initial)
    assert(not ok and reason=="locked entity","missing technology did not block placement: "..tostring(reason))
    storage.locked_rejected=true
    game.forces.player.research_all_technologies() -- Test setup; never counted as player progress.
    storage.initial_added=apply(designs.initial)
    storage.before=observe(designs.first)
  elseif event.tick==20 then
    local first
    for _,entity in pairs(designs.incremental.add) do if entity.name=="transport-belt" then first=entity; break end end
    local wall=assert(game.surfaces.nauvis.create_entity{name="stone-wall",position=first.position,force="player"})
    local ok,reason=preflight(designs.incremental)
    assert(not ok and reason=="collision","unmanaged obstacle was ignored")
    storage.obstacle_rejected=true
    wall.destroy()
    storage.incremental_added=apply(designs.incremental)
    storage.repeat_added=apply(designs.incremental)
    assert(storage.repeat_added==0,"reapplying the same additions duplicated entities")
    storage.after=observe(designs.expanded)
    for key,before in pairs(storage.before.entities) do
      assert(storage.after.entities[key].unit_number==before.unit_number,"an old entity was replaced")
    end
    for _,x in ipairs{0,24} do
      local power=assert(game.surfaces.nauvis.create_entity{name="electric-energy-interface",position={x+5,5},force="player"})
      power.electric_buffer_size=1000000000
      power.power_production=10000000
      power.energy=1000000000
    end
    storage.inserted={0,0}
  elseif event.tick>20 and event.tick<1800 and event.tick%16==0 then
    for i,x in ipairs{0,24} do
      local belt=game.surfaces.nauvis.find_entity("transport-belt",{x+.5,14.5})
      if storage.inserted[i]<100 and belt.get_transport_line(1).insert_at_back{name="iron-plate",count=1} then
        storage.inserted[i]=storage.inserted[i]+1
      end
    end
  elseif event.tick==1800 then
    local produced={}
    for key,entity in pairs(storage.managed) do
      if entity.type=="assembling-machine" then
        produced[key]=entity.products_finished
        assert(entity.products_finished>=10,"iron feed did not reach and operate the module")
      end
    end
    local old
    for key,entity in pairs(storage.managed) do if string.find(key,"main/gear-a/",1,true) and entity.type=="assembling-machine" then old=entity end end
    old.set_recipe("copper-cable")
    local ok,reason=preflight(designs.incremental)
    assert(not ok and reason=="drift","changed existing recipe was silently overwritten")
    helpers.write_file("declarative-results.json",helpers.table_to_json{
      before=storage.before,after=storage.after,drift=observe(designs.first),
      initial_added=storage.initial_added,incremental_added=storage.incremental_added,
      repeat_added=storage.repeat_added,retained_ids_preserved=true,
      obstacle_rejected=storage.obstacle_rejected,locked_rejected=storage.locked_rejected,
      drift_rejected=true,inserted_plates=storage.inserted,gear_crafts=produced,
      method="test-only creation with preflight; test research, electricity and finite supplied plates"},false)
    remote.call("blueprint-gen-observer","survey_area",game.surfaces.nauvis.index,game.forces.player.index,16,8,32)
  end
end)

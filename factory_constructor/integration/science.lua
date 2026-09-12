-- Observation and bounded player operations; the Python plan owns the layout.
local iron,adapter,walking=require("iron"),require("adapter"),require("science_walking")
local M={}
local group_names={"coal_built","feed_built","power_built","iron_built","science_built"}
local observed_items={"coal","iron-ore","iron-plate","copper-ore","copper-plate",
  "iron-gear-wheel","automation-science-pack"}

local function inventory(inv)
  local out={}
  if inv then for _,s in pairs(inv.get_contents()) do
    assert(s.quality=="normal","unsupported item quality")
    out[s.name]=(out[s.name] or 0)+s.count
  end end
  return out
end
local function copy(t) local out={};for k,v in pairs(t) do out[k]=v end;return out end
local function equal(a,b)
  for k,v in pairs(a) do if b[k]~=v then return false end end
  for k,v in pairs(b) do if a[k]~=v then return false end end
  return true
end
local function ref(e) return e and e.valid and tostring(e.unit_number) or nil end
local function resource_ref(e) return e.name..":"..e.position.x..":"..e.position.y end
local function entity_status(value)
  for k,v in pairs(defines.entity_status) do if v==value then return k end end
  return "unknown"
end
local function each_entity(fn)
  local seen={}
  for _,name in ipairs(group_names) do for address,e in pairs(storage[name] or {}) do
    assert(e.valid and e.force==storage.actor.force,"managed entity disappeared or changed force: "..address)
    local id=ref(e)
    assert(not seen[id],"managed entity has duplicate addresses")
    seen[id]=true;fn(address,e,name)
  end end
end
local function configuration(address,e)
  local out={address=address,id=ref(e),name=e.name,position=copy(e.position),direction=e.direction}
  if e.type=="furnace" or e.type=="assembling-machine" then
    local recipe=e.get_recipe();out.recipe=recipe and recipe.name or nil
  end
  return out
end
local function retained_configuration()
  local out={}
  each_entity(function(address,e,group)
    if group~="science_built" then out[address]=configuration(address,e) end
  end)
  return out
end
local function check_retained()
  local actual=retained_configuration()
  for address,expected in pairs(storage.science_retained or {}) do
    local e=assert(actual[address],"retained entity missing: "..address)
    -- A furnace selects its recipe from delivered ingredients and can clear it
    -- while empty. Recipe selection is static only for assembling machines.
    assert(e.id==expected.id and e.name==expected.name and e.direction==expected.direction
      and equal(e.position,expected.position)
      and (e.name=="stone-furnace" or e.recipe==expected.recipe),"retained entity configuration drift: "..address)
  end
  for address in pairs(actual) do
    assert(storage.science_retained[address],"unaccounted retained entity: "..address)
  end
  return actual
end
local function fuel(e)
  local contents=inventory(e.get_fuel_inventory())
  for item in pairs(contents) do assert(item=="coal","non-coal fuel in science supply network") end
  local burning=e.burner.currently_burning
  local item=burning and burning.name.name or nil
  -- Native cursor-built burner inserters receive a small initial wood charge.
  -- Record that finite reserve rather than changing native placement behavior.
  assert(not item or item=="coal" or item=="wood","unsupported item burning in science supply network")
  return {coal=contents.coal or 0,burning_j=e.burner.remaining_burning_fuel,burning_item=item}
end
local function add_meter(address,e)
  if e.burner then
    local now=fuel(e)
    storage.science_meters[address]={previous=now,delivered=0,started=0,burned_j=0,
      initial_burning_item=now.burning_item,initial_burning_j=now.burning_j}
  end
end
function M.observe_tick()
  iron.observe_tick()
  if not storage.science_meters then return end
  each_entity(function(address,e)
    local meter=storage.science_meters[address]
    if meter then
      local now=fuel(e)
      assert(now.burning_item~="wood" or (meter.initial_burning_item=="wood" and meter.started==0),
        "non-native wood appeared in science supply network: "..address)
      local starts=now.burning_j>meter.previous.burning_j+.001 and 1 or 0
      assert(starts==0 or now.burning_item=="coal","new fuel charge is not coal: "..address)
      local delivered=now.coal-meter.previous.coal+starts
      local burned=meter.previous.burning_j+starts*prototypes.item.coal.fuel_value-now.burning_j
      assert(delivered>=0 and burned>=-.001,"unaccounted science-network fuel mutation: "..address)
      meter.delivered=meter.delivered+delivered;meter.started=meter.started+starts
      meter.burned_j=meter.burned_j+math.max(0,burned);meter.previous=now
    else assert(not e.burner,"unmetered science-network burner: "..address) end
  end)
end

local function entity_sample(address,e)
  local r=configuration(address,e)
  r.type=e.type;r.active=e.active;r.status=entity_status(e.status)
  r.network_id=e.electric_network_id;r.energy_j=e.energy
  if e.burner then
    r.fuel=inventory(e.get_fuel_inventory());r.burning_j=e.burner.remaining_burning_fuel
    r.energy_usage_j_per_tick=e.prototype.energy_usage
    local burning=e.burner.currently_burning;r.burning_item=burning and burning.name.name or nil
  end
  if e.type=="mining-drill" or e.type=="inserter" then
    r.drop_target=ref(e.drop_target);r.drop_position=e.drop_position
  end
  if e.type=="mining-drill" then
    local target=e.mining_target
    r.mining_target=target and target.valid and target.name or nil
    r.mining_target_id=target and target.valid and resource_ref(target) or nil
    r.mining_area=e.mining_area;r.bonus_mining_progress=e.bonus_mining_progress
  elseif e.type=="furnace" or e.type=="assembling-machine" then
    r.input=inventory(e.get_inventory(defines.inventory.crafter_input))
    r.output=inventory(e.get_output_inventory());r.products=e.products_finished
    r.progress=e.crafting_progress;r.bonus_progress=e.bonus_progress;r.crafting_speed=e.crafting_speed
    local recipe=e.get_recipe()
    if recipe then r.recipe_definition={energy_s=recipe.energy,ingredients=recipe.ingredients,products=recipe.products} end
  elseif e.type=="inserter" then
    r.pickup_target=ref(e.pickup_target);r.pickup_position=e.pickup_position
    local s=e.held_stack;r.held=s.valid_for_read and {name=s.name,count=s.count} or nil
  elseif e.type=="container" then r.contents=inventory(e.get_inventory(defines.inventory.chest))
  elseif e.type=="transport-belt" then
    r.lanes={inventory(e.get_transport_line(1)),inventory(e.get_transport_line(2))}
    r.inputs={};r.outputs={}
    for _,target in pairs(e.belt_neighbours.inputs) do r.inputs[#r.inputs+1]=ref(target) end
    for _,target in pairs(e.belt_neighbours.outputs) do r.outputs[#r.outputs+1]=ref(target) end
    table.sort(r.inputs);table.sort(r.outputs)
  end
  return r
end
local function deposits(out)
  local seen={}
  for _,spec in ipairs(storage.science_areas or {}) do
    for _,e in pairs(storage.actor.surface.find_entities_filtered{type="resource",area=spec.area}) do
      assert(e.name==spec.resource and not e.prototype.infinite_resource,"incompatible science mining resource")
      local id=resource_ref(e)
      if not seen[id] then
        seen[id]=true
        out.deposit_remaining=out.deposit_remaining+e.amount
        out.deposit_remaining_by_resource[e.name]=(out.deposit_remaining_by_resource[e.name] or 0)+e.amount
        out.deposits[#out.deposits+1]={id=id,name=e.name,position=e.position,amount=e.amount}
      end
    end
  end
  table.sort(out.deposits,function(a,b) return a.id<b.id end)
end
local function sample(base)
  if not base then base={};iron.state(base) end
  local a=storage.actor
  local out={tick=game.tick,iron=base.iron,entities={},deposits={},deposit_remaining=0,
    deposit_remaining_by_resource={},mining_areas=storage.science_areas,production={},meters={},
    player_inventory=inventory(a.get_main_inventory()),player_position=a.position,
    coal_fuel_value_j=prototypes.item.coal.fuel_value,retained=check_retained(),
    seeds=copy(storage.science_seeds or {}),recipe_events=copy(storage.science_recipe_events or {}),
    electric_networks={},electric_consumed_j=0,electric_generated_j=0,steam_reserve_j=0,
    electric_buffer_j=0,burner_reserve_j=0,transfer_count=#storage.transfers,
    build_count=#storage.player_build_events,cursor_placement_count=#(storage.cursor_placements or {})}
  local stats=a.force.get_item_production_statistics(a.surface)
  for _,item in ipairs(observed_items) do
    out.production[item]={produced=stats.get_input_count(item),consumed=stats.get_output_count(item)}
  end
  each_entity(function(address,e,group)
    if group=="science_built" then out.entities[#out.entities+1]=entity_sample(address,e) end
    if e.burner then
      local meter=assert(storage.science_meters[address],"missing science fuel meter")
      local now=fuel(e)
      out.meters[address]={delivered=meter.delivered,started=meter.started,burned_j=meter.burned_j,
        coal=now.coal,burning_j=now.burning_j,burning_item=now.burning_item,
        initial_burning_item=meter.initial_burning_item,initial_burning_j=meter.initial_burning_j,
        energy_usage_j_per_tick=e.prototype.energy_usage}
      out.burner_reserve_j=out.burner_reserve_j+now.burning_j+now.coal*out.coal_fuel_value_j+e.energy
    elseif e.electric_network_id then out.electric_buffer_j=out.electric_buffer_j+e.energy end
    for i=1,e.fluids_count do
      local fluid=e.get_fluid(i)
      if fluid and fluid.name=="steam" then
        local p=prototypes.fluid.steam
        out.steam_reserve_j=out.steam_reserve_j+fluid.amount*math.max(0,fluid.temperature-p.default_temperature)*p.heat_capacity
      end
    end
    if e.type=="electric-pole" and e.electric_network_id then
      local id=tostring(e.electric_network_id)
      local network=out.electric_networks[id]
      if not network then
        local electric=e.electric_network_statistics
        -- In electric statistics the input side records consumers, and the
        -- output side records generators (the same convention as power.lua).
        network={id=e.electric_network_id,poles={},consumed_j=copy(electric.input_counts),
          generated_j=copy(electric.output_counts),total_consumed_j=0,total_generated_j=0}
        for _,amount in pairs(network.consumed_j) do network.total_consumed_j=network.total_consumed_j+amount end
        for _,amount in pairs(network.generated_j) do network.total_generated_j=network.total_generated_j+amount end
        out.electric_consumed_j=out.electric_consumed_j+network.total_consumed_j
        out.electric_generated_j=out.electric_generated_j+network.total_generated_j
        out.electric_networks[id]=network
      end
      network.poles[#network.poles+1]=address
    end
  end)
  for _,network in pairs(out.electric_networks) do table.sort(network.poles) end
  table.sort(out.entities,function(a,b) return a.address<b.address end)
  deposits(out)
  return out
end
function M.state(out)
  iron.state(out)
  if storage.science_areas then out.science=sample(out) end
end
local function normalise_areas(areas)
  assert(type(areas)=="table" and #areas>0,"science needs surveyed mining areas")
  local result={}
  for _,entry in ipairs(areas) do
    local area=entry.area or entry
    local resource=entry.resource or "copper-ore"
    assert(type(resource)=="string" and prototypes.entity[resource]
      and prototypes.entity[resource].type=="resource","invalid mining resource")
    assert(type(area)=="table" and #area==2,"invalid mining area")
    local bounds={}
    for i=1,2 do
      assert(type(area[i])=="table" and #area[i]==2,"invalid mining area corner")
      bounds[i]={}
      for j=1,2 do
        local value=area[i][j]
        assert(type(value)=="number" and value==value and math.abs(value)<math.huge,"invalid mining coordinate")
        bounds[i][j]=value
      end
    end
    assert(bounds[1][1]<bounds[2][1] and bounds[1][2]<bounds[2][2],"empty mining area")
    result[#result+1]={resource=resource,area=bounds}
  end
  return result
end
function M.begin(request,job)
  local a,args,op=storage.actor,request.args or {},request.op
  if op=="walk_science" then
    walking.begin(args,job)
  elseif op=="begin_science" then
    assert(not storage.science_areas and not storage.science_built,"science module already started")
    assert(storage.iron_areas and storage.iron_built,"science needs the retained iron factory")
    job.areas=normalise_areas(args.mining_areas)
  elseif op=="place_science" then
    assert(storage.science_areas,"begin_science must precede placement")
    job.spec=assert(args.spec)
    assert(type(job.spec.address)=="string" and string.sub(job.spec.address,1,8)=="science.","place_science requires a science address")
  elseif op=="seed_science" then
    assert(storage.science_areas and not storage.science_measurement_started,"seed only before science measurement")
    job.entity=assert((storage.science_built or {})[args.address],"unknown science burner")
    assert(job.entity.valid and job.entity.burner and not (storage.science_seeds or {})[args.address],"burner already seeded or invalid")
    local initial=fuel(job.entity)
    assert(job.entity.get_fuel_inventory().is_empty()
      and (initial.burning_j==0 or initial.burning_item=="wood"),"seed burner must be empty apart from native initial fuel")
    assert(type(args.coal)=="number" and args.coal>0 and args.coal==math.floor(args.coal),"invalid seed quantity")
  elseif op=="wait_science" then
    assert(storage.science_areas and args.ticks==3600,"measure science for one minute")
    job.before=sample();job.inventory=inventory(a.get_main_inventory());job.position=copy(a.position)
    job.transfers=#storage.transfers;job.builds=#storage.player_build_events
    job.cursor_placements=#(storage.cursor_placements or {});job.recipe_events=#(storage.science_recipe_events or {})
    job.deadline=game.tick+args.ticks+1
    storage.science_measurement_started=true
  else return iron.begin(request,job) end
  return true
end
function M.tick(job,walk)
  local a,args,op=storage.actor,job.request.args or {},job.request.op
  if op=="walk_science" then
    return walking.tick(job,walk)
  elseif op=="begin_science" then
    storage.science_areas=job.areas;storage.science_built={};storage.science_meters={}
    storage.science_seeds={};storage.science_recipe_events={}
    storage.science_retained=retained_configuration()
    each_entity(add_meter)
    local baseline=sample()
    assert(#baseline.deposits>0,"science mining areas contain no surveyed resources")
    storage.science_baseline=baseline
    return baseline
  elseif op=="place_science" then
    local entity,added=adapter.place(a,job.spec)
    if added then add_meter(job.spec.address,entity) end
    return {id=ref(entity),address=job.spec.address,added=added,recipe=job.spec.recipe}
  elseif op=="seed_science" then
    local before=fuel(job.entity)
    adapter.transfer(a,job.entity,a.get_main_inventory(),job.entity.get_fuel_inventory(),"coal",args.coal)
    local seed={tick=game.tick,address=args.address,id=ref(job.entity),coal=args.coal,before=before,after=fuel(job.entity)}
    storage.science_seeds[args.address]=seed
    return seed
  elseif op=="wait_science" then
    assert(equal(job.inventory,inventory(a.get_main_inventory())) and equal(job.position,a.position)
      and #storage.transfers==job.transfers and #storage.player_build_events==job.builds
      and #(storage.cursor_placements or {})==job.cursor_placements
      and #(storage.science_recipe_events or {})==job.recipe_events
      and a.crafting_queue_size==0 and not a.walking_state.walking and not a.mining_state.mining
      and a.player and not a.player.cheat_mode and not a.player.cursor_stack.valid_for_read,
      "player intervened during science measurement")
    if game.tick-job.started>=args.ticks then
      return {before=job.before,after=sample(),idle_ticks=game.tick-job.started,player_idle=true,
        inventory_before=job.inventory,inventory_after=inventory(a.get_main_inventory()),
        position_before=job.position,position_after=a.position,transfer_count=job.transfers,build_count=job.builds,
        cursor_placement_count=job.cursor_placements,recipe_event_count=job.recipe_events}
    end
  else return iron.tick(job,walk) end
end
return M

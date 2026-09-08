-- Mutating executor ONLY for the disposable opening experiment.
local ground,config,plan,adapter=require("ground"),require("config"),require("plan"),require("adapter")
local function distance(a,b) return ((a.x-b.x)^2+(a.y-b.y)^2)^.5 end
local function equal(a,b)
  if type(a)~=type(b) then return false end
  if type(a)~="table" then return a==b end
  for k,v in pairs(a) do if not equal(v,b[k]) then return false end end
  for k,_ in pairs(b) do if a[k]==nil then return false end end
  return true
end
local function write(name,value) helpers.write_file(name..".json",helpers.table_to_json(value),false) end
local function contents(inventory)
  local result={}
  for _,s in pairs(inventory.get_contents()) do
    assert(s.quality=="normal","unsupported quality")
    result[s.name]=(result[s.name] or 0)+s.count
  end
  return result
end
local function observe(sites)
  local actor=storage.actor
  local researched={}
  for name,technology in pairs(actor.force.technologies) do if technology.researched then researched[#researched+1]=name end end
  table.sort(researched)
  local state={tick=game.tick,active_mods=script.active_mods,character_id=tostring(actor.unit_number),
    surface_index=actor.surface.index,force_index=actor.force.index,map_seed=actor.surface.map_gen_settings.seed,
    position=actor.position,inventory=contents(actor.get_main_inventory()),researched=researched,
    build_distance=actor.build_distance,reach_distance=actor.reach_distance,
    produced_iron=actor.force.get_item_production_statistics(actor.surface).get_input_count("iron-plate")}
  if sites then
    state.furnace_sites={}
    for x=math.floor(actor.position.x)-6,math.floor(actor.position.x)+6 do
      for y=math.floor(actor.position.y)-6,math.floor(actor.position.y)+6 do
        local p={x=x,y=y}
        if adapter.site(actor,p) then state.furnace_sites[#state.furnace_sites+1]=p end
      end
    end
  end
  return state
end
local function survey()
  local a=storage.actor
  remote.call("blueprint-gen-observer","survey_area",a.surface.index,a.force.index,a.position.x,a.position.y,64)
end

script.on_event(defines.events.on_chunk_generated,ground.chunk_generated)
script.on_init(function()
  ground.init()
  storage.actor=assert(game.surfaces.nauvis.create_entity{name="character",position=config.spawn,force="player"})
  ground.give_inventory(storage.actor)
  storage.leg=1
  storage.built={}
  storage.paid_furnaces=0
  storage.transfers={}
  storage.mining={}
  storage.walked=0
  storage.previous=storage.actor.position
end)

local directions={ ["0,-1"]=defines.direction.north,["1,-1"]=defines.direction.northeast,
  ["1,0"]=defines.direction.east,["1,1"]=defines.direction.southeast,["0,1"]=defines.direction.south,
  ["-1,1"]=defines.direction.southwest,["-1,0"]=defines.direction.west,["-1,-1"]=defines.direction.northwest }
local function gather_tick()
  local actor=storage.actor
  local target=plan.targets[storage.leg]
  if not target then return true end
  local route=plan.routes[storage.leg]
  if not storage.requested then
    local resource=actor.surface.find_entities_filtered{type="resource",name=target.item,position=target.position,radius=.01}[1]
    assert(resource and resource.amount==target.observed_resource_units,"resource changed; replan")
    storage.resource=resource
    storage.initial_amount=resource.amount
    storage.initial_count=actor.get_main_inventory().get_item_count(target.item)
    storage.requested=game.tick
    write("checkpoint-"..storage.leg,observe())
    remote.call("blueprint-gen-observer","route_character",actor,target.position.x,target.position.y,target.quantity)
    storage.waypoint=2
  end
  if not route then return false end -- Python must compile this newly observed checkpoint.
  assert(route.requested_tick==storage.requested,"replay timing changed; replan")
  if game.tick<=route.based_on_tick then return false end
  if not storage.walk_started then
    assert(game.tick-route.based_on_tick<=600,"stale route")
    assert(distance(actor.position,route.waypoints[1])<.001,"character moved; replan")
    assert(tostring(actor.unit_number)==route.character_id,"different character; replan")
    storage.walk_started=game.tick
  end
  local point=route.waypoints[storage.waypoint]
  if point then
    if distance(actor.position,point)<=.12 then
      actor.walking_state={walking=false,direction=defines.direction.north}
      storage.waypoint=storage.waypoint+1
    else
      local dx,dy=point.x-actor.position.x,point.y-actor.position.y
      local h=math.abs(dx)>.08 and (dx>0 and 1 or -1) or 0
      local v=math.abs(dy)>.08 and (dy>0 and 1 or -1) or 0
      actor.walking_state={walking=true,direction=assert(directions[h..","..v])}
    end
    return false
  end
  actor.walking_state={walking=false,direction=defines.direction.north}
  assert(actor.can_reach_entity(storage.resource),"mineral out of reach")
  local gained=actor.get_main_inventory().get_item_count(target.item)-storage.initial_count
  if gained>=target.quantity then
    actor.mining_state={mining=false}
    assert(gained==target.quantity and storage.initial_amount-storage.resource.amount==gained,"mining conservation failed")
    storage.mining[#storage.mining+1]={item=target.item,gained=gained,depleted=storage.initial_amount-storage.resource.amount,
      receipt_sha256=route.receipt_sha256,started_tick=storage.walk_started,finished_tick=game.tick}
    storage.leg=storage.leg+1
    storage.requested=nil
    storage.walk_started=nil
  else
    actor.update_selected_entity(storage.resource.position)
    assert(actor.selected==storage.resource,"mineral selection intercepted")
    actor.mining_state={mining=true,position=storage.resource.position}
  end
  return false
end

local function refusal(kind,fn)
  local before=contents(storage.actor.get_main_inventory())
  local ok,err=pcall(fn)
  assert(not ok and string.find(tostring(err),kind,1,true),"expected refusal "..kind..": "..tostring(err))
  assert(equal(contents(storage.actor.get_main_inventory()),before),"refusal changed inventory")
  storage.refusals[kind]=true
end
local function smelt_tick()
  local actor=storage.actor
  if not storage.placement_observed then
    local state=observe(true)
    write("placement-state",state)
    survey()
    storage.placement_observed=true
    if not plan.placement then return end
    assert(equal(state,plan.placement_state),"placement checkpoint changed; replan")
  end
  if not plan.placement then return end
  if not storage.furnace then
    storage.refusals={}
    refusal("out_of_reach",function() adapter.place(actor,{address="far",name="stone-furnace",direction=0,position={x=500,y=500}}) end)
    refusal("collision",function() adapter.place(actor,{address="occupied",name="stone-furnace",direction=0,
      position={x=math.floor(actor.position.x+.5),y=math.floor(actor.position.y+.5)}}) end)
    storage.furnace=adapter.place(actor,plan.placement)
    local same,added=adapter.place(actor,plan.placement)
    storage.retained=same==storage.furnace and not added
    local spare
    for _,p in ipairs(plan.placement_state.furnace_sites) do if adapter.site(actor,p) then spare=p; break end end
    assert(spare,"no second site for missing-item refusal probe")
    refusal("missing_item",function() adapter.place(actor,{address="unpaid",name="stone-furnace",direction=0,position=spare}) end)
    local main,input=actor.get_main_inventory(),storage.furnace.get_inventory(defines.inventory.crafter_input)
    refusal("short_transfer",function() adapter.transfer(actor,storage.furnace,main,input,"iron-ore",51) end)
    adapter.transfer(actor,storage.furnace,main,input,"iron-ore",plan.smelt.inputs["iron-ore"])
    adapter.transfer(actor,storage.furnace,main,storage.furnace.get_fuel_inventory(),"coal",plan.smelt.coal)
    storage.loaded_tick=game.tick
    return
  end
  local furnace=storage.furnace
  assert(game.tick-storage.loaded_tick<=plan.smelt.processing_seconds*60+180,"smelting exceeded its tick budget")
  if furnace.products_finished<plan.smelt.crafts then return end
  assert(furnace.products_finished==plan.smelt.crafts,"unexpected extra crafts")
  if not storage.collected_tick then
    adapter.transfer(actor,furnace,furnace.get_output_inventory(),actor.get_main_inventory(),"iron-plate",50)
    storage.collected_tick=game.tick
    return
  end
  -- Technology triggers can be processed after the crafting tick. Observe them;
  -- never set researched, research_progress or production statistics in this test.
  if not actor.force.technologies["steam-power"].researched and game.tick-storage.collected_tick<120 then return end
  write("execution",{final=observe(),mining=storage.mining,transfers=storage.transfers,
    furnace={address=plan.placement.address,unit_number=furnace.unit_number,position=furnace.position,
      products_finished=furnace.products_finished,input=contents(furnace.get_inventory(defines.inventory.crafter_input)),
      output=contents(furnace.get_output_inventory()),fuel=contents(furnace.get_fuel_inventory()),
      remaining_burning_fuel_j=furnace.burner.remaining_burning_fuel},
    paid_furnaces=storage.paid_furnaces,retained_on_repeat=storage.retained,refusals=storage.refusals,
    walking_distance=storage.walked,smelting_ticks=storage.collected_tick-storage.loaded_tick,
    trigger_wait_ticks=game.tick-storage.collected_tick,
    method="native walking_state/mining_state; costed test placement and reach-checked transfers; ordinary furnace ticks"})
  survey()
  storage.finished=true
end

script.on_event(defines.events.on_tick,function(event)
  if event.tick<120 or storage.finished then return end
  local position=storage.actor.position
  storage.walked=storage.walked+distance(position,storage.previous)
  storage.previous=position
  if event.tick==120 then write("initial-state",observe()); survey(); return end
  if not plan.targets then return end
  if gather_tick() then smelt_tick() end
end)

-- Disposable live executor. Separate from the read-only observer and replay experiment.
local ground,config,adapter=require("ground"),require("config"),require("adapter")
local extension=require("extension")
local function distance(a,b) return ((a.x-b.x)^2+(a.y-b.y)^2)^.5 end
local function equal(a,b)
  if type(a)~=type(b) then return false end
  if type(a)~="table" then return a==b end
  for k,v in pairs(a) do if not equal(v,b[k]) then return false end end
  for k,_ in pairs(b) do if a[k]==nil then return false end end
  return true
end
local function inventory(inv)
  local out={}
  for _,s in pairs(inv.get_contents()) do assert(s.quality=="normal");out[s.name]=(out[s.name] or 0)+s.count end
  return out
end
local function entities()
  local out={}
  for address,e in pairs(storage.built) do
    assert(e.valid,"built entity disappeared")
    out[#out+1]={address=address,id=tostring(e.unit_number),name=e.name,position=e.position,
      crafts=e.products_finished,progress=e.crafting_progress,fuel_j=e.burner.remaining_burning_fuel,
      input=inventory(e.get_inventory(defines.inventory.crafter_input)),output=inventory(e.get_output_inventory()),
      fuel=inventory(e.get_fuel_inventory())}
  end
  return out
end
local function state(sites)
  local a=storage.actor
  local researched={}
  for n,t in pairs(a.force.technologies) do if t.researched then researched[#researched+1]=n end end
  table.sort(researched)
  local stats=a.force.get_item_production_statistics(a.surface)
  local crafted={}
  for _,name in ipairs({"iron-plate","copper-plate","lab"}) do crafted[name]=stats.get_input_count(name) end
  local out={tick=game.tick,revision=storage.revision,active_mods=script.active_mods,character_id=tostring(a.unit_number),
    surface_index=a.surface.index,force_index=a.force.index,map_seed=a.surface.map_gen_settings.seed,position=a.position,
    inventory=inventory(a.get_main_inventory()),researched=researched,crafted=crafted,produced_iron=crafted["iron-plate"],
    build_distance=a.build_distance,reach_distance=a.reach_distance,built=entities(),paid_furnaces=storage.paid_furnaces,
    paused=game.tick_paused,speed=game.speed}
  if sites then
    out.furnace_sites={}
    for x=math.floor(a.position.x)-6,math.floor(a.position.x)+6 do
      for y=math.floor(a.position.y)-6,math.floor(a.position.y)+6 do
        local p={x=x,y=y};if adapter.site(a,p) then out.furnace_sites[#out.furnace_sites+1]=p end
      end
    end
  end
  if extension.state then extension.state(out) end
  return out
end
local function frame(event)
  storage.frame=storage.frame+1
  local s=state()
  s.frame=storage.frame;s.event=event;s.action=storage.job and storage.job.request or storage.last_action
  if storage.trace_mode~="full" then
    -- The complete ledgers remain in observations and native event files.
    -- Repeating their entire history at every boundary adds no new evidence.
    s.cursor_placements=nil;s.player_build_events=nil;s.tree_events=nil;s.coal_seed=nil
  end
  helpers.write_file("live-trace.jsonl",helpers.table_to_json(s).."\n",true)
end
local function finish(value,err)
  local job=storage.job
  storage.actor.walking_state={walking=false,direction=defines.direction.north}
  storage.actor.mining_state={mining=false}
  game.tick_paused=true
  storage.revision=storage.revision+1
  storage.commands[job.request.id].outcome={status=err and "failed" or "done",value=value,error=err,
    started_tick=job.started,finished_tick=game.tick,revision=storage.revision}
  storage.last_action=job.request
  frame(err and "failed" or "done")
  storage.job=nil
end
script.on_event(defines.events.on_chunk_generated,ground.chunk_generated)
script.on_init(function()
  ground.init()
  storage.actor=assert(game.surfaces.nauvis.create_entity{name="character",position=config.spawn,force="player"})
  ground.give_inventory(storage.actor)
  storage.built={};storage.paid_furnaces=0;storage.transfers={};storage.commands={};storage.revision=1;storage.frame=0
  game.tick_paused=true
  helpers.write_file("live-world.json",helpers.table_to_json{config=config,active_mods=script.active_mods,
    source="actual disposable Factorio state; overview rendering is not game footage"},false)
end)

-- The same conservative swept-character-box check used by the observer, applied
-- to furnace approaches (the observer's public routes deliberately target minerals only).
local function checked_path(path,start)
  assert(path and #path>0 and #path<=2048,"no bounded native path")
  if distance(path[1].position,start)>.001 then table.insert(path,1,{position=start,needs_destroy_to_reach=false}) end
  local actor,box=storage.actor,storage.actor.prototype.collision_box
  local layers=actor.prototype.collision_mask.layers
  local total=0
  for i,p in ipairs(path) do
    assert(not p.needs_destroy_to_reach,"path requires destruction")
    if i>1 then
      local a,b=path[i-1].position,p.position
      total=total+distance(a,b);assert(total<=256,"path too long")
      local n=math.max(1,math.ceil(distance(a,b)/.125))
      for j=1,n do
        local x0,y0=a.x+(b.x-a.x)*(j-1)/n,a.y+(b.y-a.y)*(j-1)/n
        local x1,y1=a.x+(b.x-a.x)*j/n,a.y+(b.y-a.y)*j/n
        local area={{math.min(x0,x1)+box.left_top.x,math.min(y0,y1)+box.left_top.y},
          {math.max(x0,x1)+box.right_bottom.x,math.max(y0,y1)+box.right_bottom.y}}
        assert(#actor.surface.find_tiles_filtered{area=area,collision_mask=layers,limit=1}==0,"path crosses terrain")
        for _,e in pairs(actor.surface.find_entities_filtered{area=area,collision_mask=layers}) do
          assert(e==actor,"path intersects entity")
        end
      end
    end
  end
  return path
end
local directions={["0,-1"]=0,["1,-1"]=2,["1,0"]=4,["1,1"]=6,["0,1"]=8,["-1,1"]=10,["-1,0"]=12,["-1,-1"]=14}
local function walk(job)
  local p=job.path[job.waypoint]
  if not p then storage.actor.walking_state={walking=false,direction=0};return true end
  p=p.position
  local a=storage.actor.position
  if distance(a,p)<=.12 then
    storage.actor.walking_state={walking=false,direction=0};job.waypoint=job.waypoint+1
  else
    local dx,dy=p.x-a.x,p.y-a.y
    local h=math.abs(dx)>.08 and (dx>0 and 1 or -1) or 0
    local v=math.abs(dy)>.08 and (dy>0 and 1 or -1) or 0
    storage.actor.walking_state={walking=true,direction=assert(directions[h..","..v])}
  end
  return false
end
local function amount(value)
  assert(type(value)=="number" and value==math.floor(value) and value>0 and value<=1000,"invalid item count")
  return value
end
local function recipe(name,count)
  local r=assert(storage.actor.force.recipes[name],"unknown recipe")
  assert(r.enabled,"recipe is locked")
  local inputs,outputs={},{}
  for _,i in pairs(r.ingredients) do assert(i.type=="item");inputs[i.name]=i.amount*count end
  for _,i in pairs(r.products) do
    assert(i.type=="item" and i.amount and (not i.probability or i.probability==1),"unsupported recipe products")
    outputs[i.name]=i.amount*count
  end
  return r,inputs,outputs
end
local function require_stock(needed)
  local inv=storage.actor.get_main_inventory()
  for item,count in pairs(needed) do assert(inv.get_item_count(item)>=count,"missing item: "..item) end
end
local function begin(request)
  local a,args=storage.actor,request.args or {}
  local op=request.op
  local job={request=request,started=game.tick,deadline=game.tick+24000}
  if op=="route" then
    job.start=a.position
    local target=assert(args.target)
    local result=remote.call("blueprint-gen-observer","route_character",a,target.position.x,target.position.y,amount(target.quantity))
    job.sequence=result.sequence;job.request_id=result.request_id
    job.resource=assert(a.surface.find_entities_filtered{type="resource",name=target.item,position=target.position,radius=.01}[1])
    job.resource_amount=job.resource.amount;job.target=target
    if not result.request_id then job.path={{position=a.position}} end
  elseif op=="mine" then
    local route=assert(storage.last_route,"request a native route first")
    assert(route.sequence==args.sequence and distance(a.position,route.start)<.001,"route start changed")
    assert(game.tick-route.completed<=600 and route.resource.valid and route.resource.amount==route.resource_amount,"route is stale")
    job.path=route.path;job.waypoint=2;job.resource=route.resource;job.target=route.target
    job.before=a.get_main_inventory().get_item_count(job.target.item);job.resource_amount=job.resource.amount
    assert(a.get_main_inventory().can_insert{name=job.target.item,count=job.target.quantity},"inventory is full")
  elseif op=="place" then
    job.spec=args.spec
  elseif op=="approach" then
    job.entity=assert(storage.built[args.address],"unknown station")
    assert(job.entity.valid and distance(a.position,job.entity.position)<=64,"station beyond approach range")
    if a.can_reach_entity(job.entity) then job.path={{position=a.position}};job.waypoint=2
    else
      local box=a.prototype.collision_box
      local mask={layers={},consider_tile_transitions=false}
      for k,v in pairs(a.prototype.collision_mask.layers) do mask.layers[k]=v end
      mask.layers.water_tile=true
      job.start=a.position
      job.request_id=a.surface.request_path{bounding_box={{box.left_top.x-.25,box.left_top.y-.25},{box.right_bottom.x+.25,box.right_bottom.y+.25}},
        collision_mask=mask,start=a.position,goal=job.entity.position,force=a.force,radius=a.reach_distance-1,
        entity_to_ignore=a,can_open_gates=false,max_gap_size=0,path_resolution_modifier=1,
        pathfind_flags={allow_destroy_friendly_entities=false,allow_paths_through_own_entities=false,cache=false,prefer_straight_paths=true}}
    end
  elseif op=="smelt" then
    job.entity=assert(storage.built[args.address],"unknown station")
    assert(a.can_reach_entity(job.entity),"station out of reach")
    local count=amount(args.crafts)
    local r,inputs,outputs=recipe(args.recipe,count)
    assert(args.recipe=="iron-plate" or args.recipe=="copper-plate","unsupported smelting recipe")
    local needed={};for item,n in pairs(inputs) do needed[item]=n end
    needed.coal=(needed.coal or 0)+amount(args.coal);require_stock(needed)
    assert(job.entity.get_inventory(defines.inventory.crafter_input).is_empty() and job.entity.get_output_inventory().is_empty()
      and job.entity.crafting_progress==0,"station has unfinished work")
    job.before=job.entity.products_finished;job.count=count;job.inputs=inputs;job.outputs=outputs
    job.deadline=game.tick+math.ceil(r.energy*count*60)+180
  elseif op=="handcraft" then
    local r,inputs,outputs=recipe(args.recipe,amount(args.crafts))
    local allowed=false
    for _,category in pairs(prototypes.recipe[args.recipe].categories) do if category=="crafting" then allowed=true end end
    assert(allowed,"unsupported handcraft category")
    require_stock(inputs)
    assert(a.crafting_queue_size==0,"existing crafting queue")
    job.expected=inventory(a.get_main_inventory())
    for item,n in pairs(inputs) do job.expected[item]=job.expected[item]-n;if job.expected[item]==0 then job.expected[item]=nil end end
    for item,n in pairs(outputs) do job.expected[item]=(job.expected[item] or 0)+n end
    job.deadline=game.tick+math.ceil(r.energy*args.crafts*60)+120
  elseif op=="research" then
    assert(a.force.technologies[args.technology],"unknown technology")
    job.deadline=game.tick+600
  elseif not (extension.begin and extension.begin(request,job)) then error("unsupported operation") end
  storage.commands[request.id]={request=request,outcome={status="running"}}
  storage.revision=storage.revision+1;storage.job=job
  frame("start")
  game.tick_paused=false
end

local function tick()
  local job,a=storage.job,storage.actor
  if job.request.op=="research" and game.tick>=job.deadline and not a.force.technologies[job.request.args.technology].researched then
    finish({technology=job.request.args.technology,observed=false,reason="research was not observed within 600 ticks"})
    return
  end
  assert(game.tick<=job.deadline,"action tick budget exceeded")
  local args,op=job.request.args or {},job.request.op
  if op=="route" then
    if job.path then
      storage.last_route={sequence=job.sequence,path=job.path,start=job.start,completed=game.tick,
        target=job.target,resource=job.resource,resource_amount=job.resource_amount}
      finish({sequence=job.sequence,character_id=tostring(a.unit_number)})
    end
  elseif op=="mine" then
    if not walk(job) then return end
    local gained=a.get_main_inventory().get_item_count(job.target.item)-job.before
    if gained>=job.target.quantity then
      local remaining=job.resource.valid and job.resource.amount or 0
      assert(gained==job.target.quantity and job.resource_amount-remaining==gained,"mining conservation failed")
      finish({item=job.target.item,gained=gained,depleted=job.resource_amount-remaining,sequence=args.sequence})
    else
      assert(job.resource.valid and a.can_reach_entity(job.resource),"mineral is out of reach")
      a.update_selected_entity(job.resource.position);assert(a.selected==job.resource,"selection intercepted")
      a.mining_state={mining=true,position=job.resource.position}
    end
  elseif op=="place" then
    local e,added=adapter.place(a,job.spec);finish({id=tostring(e.unit_number),added=added,address=job.spec.address})
  elseif op=="approach" then
    if job.path and walk(job) then
      assert(a.can_reach_entity(job.entity),"station remains out of reach")
      finish({id=tostring(job.entity.unit_number),position=a.position,path=job.path})
    end
  elseif op=="smelt" then
    if not job.loaded then
      for item,n in pairs(job.inputs) do adapter.transfer(a,job.entity,a.get_main_inventory(),job.entity.get_inventory(defines.inventory.crafter_input),item,n) end
      adapter.transfer(a,job.entity,a.get_main_inventory(),job.entity.get_fuel_inventory(),"coal",args.coal)
      job.loaded=game.tick
    elseif job.entity.products_finished-job.before>=job.count then
      assert(job.entity.products_finished-job.before==job.count,"unexpected crafts")
      for item,n in pairs(job.outputs) do adapter.transfer(a,job.entity,job.entity.get_output_inventory(),a.get_main_inventory(),item,n) end
      finish({station_id=tostring(job.entity.unit_number),crafts=job.count,outputs=job.outputs,smelting_ticks=game.tick-job.loaded})
    end
  elseif op=="handcraft" then
    if not job.queued then
      assert(a.begin_crafting{recipe=args.recipe,count=args.crafts,silent=true}==args.crafts,"craft queue rejected")
      job.queued=game.tick
    elseif a.crafting_queue_size==0 then
      assert(equal(inventory(a.get_main_inventory()),job.expected),"handcraft inventory differs from recipe accounting")
      finish({recipe=args.recipe,crafts=args.crafts,crafting_ticks=game.tick-job.queued})
    end
  elseif op=="research" and a.force.technologies[args.technology].researched then
    finish({technology=args.technology,observed=true})
  elseif extension.tick then
    local result=extension.tick(job,walk)
    if result then finish(result) end
  end
end
script.on_event(defines.events.on_tick,function()
  if not storage.job then game.tick_paused=true;return end
  if storage.trace_mode=="full" and game.tick%30==0 then frame("sample") end
  local ok,err=pcall(tick)
  if not ok then finish(nil,tostring(err)) end
end)
script.on_event(defines.events.on_script_path_request_finished,function(event)
  local job=storage.job
  if not job or job.request_id~=event.id then return end
  local ok,err=pcall(function()
    assert(not event.try_again_later,"pathfinder busy; request again")
    assert(distance(storage.actor.position,job.start)<.001,"character moved during pathfinding")
    job.path=checked_path(event.path,job.start);job.waypoint=2
  end)
  if not ok then finish(nil,tostring(err)) end
end)

remote.add_interface("opening-executor",{call=function(request)
  local ok,result=pcall(function()
    if request.op=="configure_trace" then
      assert(not storage.job and game.tick_paused,"configure at an idle boundary")
      assert(request.mode=="full" or request.mode=="boundaries","unknown trace mode")
      storage.trace_mode=request.mode;return {mode=storage.trace_mode}
    end
    if request.op=="checkpoint_state" then
      assert(not storage.job and game.tick_paused,"checkpoint at an idle boundary")
      local count=0;for _ in pairs(storage.commands) do count=count+1 end
      return {state=state(),command_count=count,last_command_id=storage.last_action and storage.last_action.id}
    end
    if request.op=="status" then return request.id and assert(storage.commands[request.id],"unknown command").outcome or state() end
    if request.op=="observe" then
      assert(not storage.job and game.tick_paused,"observe at a paused boundary")
      local a=storage.actor
      local path=remote.call("blueprint-gen-observer","survey_area",a.surface.index,a.force.index,a.position.x,a.position.y,64)
      frame("observe")
      return {state=state(true),capture_path=path,transfers=storage.transfers}
    end
    if request.op=="speed" then
      assert(not storage.job and game.tick_paused,"change speed at a paused boundary")
      assert(request.speed==1 or request.speed==10 or request.speed==40,"supported speeds: 1, 10, 40")
      game.speed=request.speed;return state()
    end
    if request.op=="save" then
      assert(not storage.job and game.tick_paused,"save at a paused boundary")
      assert(type(request.name)=="string" and string.match(request.name,"^[a-zA-Z0-9_-]+$"),"invalid checkpoint name")
      game.server_save(request.name);return state()
    end
    assert(type(request.id)=="string" and #request.id>0 and #request.id<=100,"command requires a bounded id")
    local previous=storage.commands[request.id]
    if previous then assert(equal(previous.request,request),"command id reused with different payload");return previous.outcome end
    assert(not storage.job and game.tick_paused,"another action is running")
    assert(request.revision==storage.revision and request.tick==game.tick,"stale checkpoint; observe again")
    begin(request)
    return storage.commands[request.id].outcome
  end)
  return ok and {ok=true,value=result} or {ok=false,error=tostring(result)}
end})

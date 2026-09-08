-- Test-only world construction and character controller. Never packaged with the observer.
local plan = require("route_plan")
local function distance(a,b) return ((a.x-b.x)^2+(a.y-b.y)^2)^0.5 end

script.on_init(function()
  local surface,force=game.surfaces[1],game.forces.player
  surface.request_to_generate_chunks({0,0},2)
  surface.force_generate_chunk_requests()
  for _,e in pairs(surface.find_entities_filtered{area={{-40,-40},{40,40}}}) do e.destroy() end
  local tiles={}
  for x=-40,40 do for y=-40,40 do tiles[#tiles+1]={name="grass-1",position={x,y}} end end
  for y=-6,6 do tiles[#tiles+1]={name="water",position={0,y}} end
  -- An ore island with enough water around it to prevent mining from the bank.
  for x=-17,-9 do for y=-15,-7 do tiles[#tiles+1]={name="water",position={x,y}} end end
  tiles[#tiles+1]={name="grass-1",position={-13,-11}}
  surface.set_tiles(tiles)
  storage.ore=assert(surface.create_entity{name="iron-ore",position={8.5,0.5},amount=20})
  storage.island=assert(surface.create_entity{name="stone",position={-12.5,-10.5},amount=20})
  storage.nearby=assert(surface.create_entity{name="coal",position={-17.5,10.5},amount=20})
  local function character(x,y) return assert(surface.create_entity{name="character",position={x,y},force=force}) end
  storage.actor=character(-8.5,0.5)
  storage.island_actor=character(-12.5,-4.5)
  storage.moved_actor=character(-4.5,-2.5)
  storage.near_actor=character(-18.5,10.5)
  storage.changed_actor=character(-8.5,7.5)
  storage.wall=assert(surface.create_entity{name="stone-wall",position={-5.5,3.5},force=force})
  storage.surface,storage.force=surface.index,force.index
  storage.waypoint=2
  storage.walked=0
  storage.previous=storage.actor.position
  storage.trace={}
end)

local function route(actor,target,quantity)
  return remote.call("blueprint-gen-observer","route_character",actor,target.position.x,target.position.y,quantity)
end

local function execution_tick(event)
  if event.tick<10 or storage.finished then return end
  local actor=storage.actor
  local location=actor.position
  storage.walked=storage.walked+distance(location,storage.previous)
  storage.previous=location
  if event.tick%10==0 then storage.trace[#storage.trace+1]=location end
  if not storage.begun then
    assert(distance(location,plan.waypoints[1])<0.001,"Execution start differs from planned start")
    assert(plan.target.item==storage.ore.name and distance(plan.target.position,storage.ore.position)<0.001,"Execution target differs")
    storage.initial_amount=storage.ore.amount
    storage.begun=event.tick
  end
  local target=plan.waypoints[storage.waypoint]
  if target then
    local dx,dy=target.x-location.x,target.y-location.y
    if distance(location,target)<=0.12 then
      actor.walking_state={walking=false,direction=defines.direction.north}
      storage.waypoint=storage.waypoint+1
    else
      local horizontal=math.abs(dx)>0.08 and (dx>0 and 1 or -1) or 0
      local vertical=math.abs(dy)>0.08 and (dy>0 and 1 or -1) or 0
      local directions={ ["0,-1"]=defines.direction.north,["1,-1"]=defines.direction.northeast,
        ["1,0"]=defines.direction.east,["1,1"]=defines.direction.southeast,["0,1"]=defines.direction.south,
        ["-1,1"]=defines.direction.southwest,["-1,0"]=defines.direction.west,["-1,-1"]=defines.direction.northwest }
      local direction=assert(directions[horizontal..","..vertical],"Controller could not select walking direction")
      actor.walking_state={walking=true,direction=direction}
    end
  else
    actor.walking_state={walking=false,direction=defines.direction.north}
    assert(actor.can_reach_entity(storage.ore),"Actual character cannot reach the planned mineral")
    local count=actor.get_main_inventory().get_item_count(plan.target.item)
    if count>=plan.target.quantity then
      actor.mining_state={mining=false}
      assert(count==plan.target.quantity,"Mining exceeded the requested count")
      assert(storage.initial_amount-storage.ore.amount==count,"Inventory gain does not match resource depletion")
      storage.finished=true
      helpers.write_file("route-execution-results.json",helpers.table_to_json{
        actual_inventory=count,resource_depletion=storage.initial_amount-storage.ore.amount,
        wall_preserved=storage.wall.valid,
        target=plan.target,final_position=actor.position,can_reach=true,
        walking_distance=storage.walked,started_tick=storage.begun,finished_tick=event.tick,
        waypoint_count=#plan.waypoints,waypoints_reached=storage.waypoint-1,trace=storage.trace,
        receipt_sha256=plan.receipt_sha256,method="walking_state plus mining_state; no teleport or instant mine"},false)
    else
      actor.update_selected_entity(storage.ore.position)
      assert(actor.selected==storage.ore,"Cursor does not select the requested mineral")
      actor.mining_state={mining=true,position=storage.ore.position}
    end
  end
end

script.on_event(defines.events.on_tick,function(event)
  if plan.waypoints then execution_tick(event); return end
  if event.tick==119 then
    remote.call("blueprint-gen-observer","survey_area",storage.surface,storage.force,-8.5,0.5,24)
  elseif event.tick==120 then
    route(storage.actor,storage.ore,3)
  elseif event.tick==200 then
    route(storage.island_actor,storage.island,1)
  elseif event.tick==300 then
    route(storage.moved_actor,storage.ore,1)
    storage.moved_actor.teleport({-4.5,-3.5}) -- Deliberate invalidation; unrelated to the execution phase.
  elseif event.tick==400 then
    route(storage.near_actor,storage.nearby,2)
  elseif event.tick==500 then
    -- A walkable belt can still intercept selection of the mineral beneath it.
    local belt=assert(game.surfaces[storage.surface].create_entity{
      name="transport-belt",position=storage.nearby.position,force=storage.force})
    local ok,reason=pcall(route,storage.near_actor,storage.nearby,2)
    assert(not ok and string.find(tostring(reason),"covered by an obstacle",1,true),
      "Covered mineral target was not rejected before pathfinding")
    helpers.write_file("route-preflight-results.json",helpers.table_to_json{
      covered_target_rejected=true,covering_entity=belt.name,reason=tostring(reason)},false)
  elseif event.tick==900 then
    route(storage.changed_actor,storage.ore,1)
    local wall=game.surfaces[storage.surface].create_entity{name="stone-wall",position={-20,-20},force=storage.force}
    script.raise_event(defines.events.script_raised_built,{entity=wall})
  end
end)

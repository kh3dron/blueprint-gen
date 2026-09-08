-- Read-only native path requests. Character movement/mining exists only in test scenarios.
local M = {}
local minerals = {["iron-ore"]=true, ["copper-ore"]=true, coal=true, stone=true}
local margin = 0.25

local function distance(a,b)
  return ((a.x-b.x)^2+(a.y-b.y)^2)^0.5
end

local function tell(actor,message)
  if actor and actor.valid and actor.player then actor.player.print(message) else log(message) end
end

local function write(request,status,reasons,path,generation)
  local record = request.record
  record.status,record.reasons,record.path=status,reasons or {},path or {}
  record.completed_tick,record.generation_at_completion=game.tick,generation
  local filename="blueprint-gen-observer/route-character-"..record.actor.id.."-request-"..record.sequence..".json"
  local recipient
  if request.actor.valid and request.actor.player then
    recipient=request.actor.player.connected and request.actor.player.index or 0
  end
  helpers.write_file(filename,helpers.table_to_json(record),false,recipient)
  tell(request.actor,"Advisor route "..status..": script-output/"..filename)
  return record
end

local function validate_end(request,generation)
  local actor,resource,record=request.actor,request.resource,request.record
  local reasons={}
  if generation~=record.generation then reasons[#reasons+1]="world configuration changed during pathfinding" end
  if not actor.valid then
    reasons[#reasons+1]="character disappeared"
  elseif actor.surface.index~=record.surface_index or actor.force.index~=record.force_index
    or actor.name~=record.actor.prototype or actor.driving or distance(actor.position,record.start)>0.001
    or actor.resource_reach_distance~=record.actor.resource_reach_distance then
    reasons[#reasons+1]="character moved or changed during pathfinding"
  end
  if not resource.valid or resource.amount~=record.target.amount or not resource.minable
    or resource.name~=record.target.prototype or distance(resource.position,record.target.position)>0.001 then
    reasons[#reasons+1]="resource changed during pathfinding"
  end
  return reasons
end

local function check_path(request,path)
  local actor=request.actor
  local box=actor.prototype.collision_box
  local layers=actor.prototype.collision_mask.layers
  -- Each box encloses the entire moving character over a short segment, including
  -- between samples. Ignore only the requesting character, never other obstacles.
  for i=2,#path do
    local a,b=path[i-1].position,path[i].position
    local divisions=math.max(1,math.ceil(distance(a,b)/0.125))
    for j=1,divisions do
      local x0,y0=a.x+(b.x-a.x)*(j-1)/divisions,a.y+(b.y-a.y)*(j-1)/divisions
      local x1,y1=a.x+(b.x-a.x)*j/divisions,a.y+(b.y-a.y)*j/divisions
      local area={{math.min(x0,x1)+box.left_top.x,math.min(y0,y1)+box.left_top.y},
                  {math.max(x0,x1)+box.right_bottom.x,math.max(y0,y1)+box.right_bottom.y}}
      if #actor.surface.find_tiles_filtered{area=area,collision_mask=layers,limit=1}>0 then
        return false,"native path crosses colliding terrain"
      end
      for _,entity in pairs(actor.surface.find_entities_filtered{area=area,collision_mask=layers}) do
        if entity~=actor then return false,"native path intersects an entity: "..entity.name end
      end
    end
  end
  return true
end

function M.start(actor,x,y,quantity,generation)
  assert(actor and actor.valid and actor.type=="character" and actor.name=="character", "A normal character is required.")
  assert(not actor.driving, "Leave the vehicle before requesting a walking approach.")
  for name in pairs(script.active_mods) do
    assert(name=="base" or name=="blueprint-gen-observer", "Routes currently support base plus observer only.")
  end
  assert(actor.surface.name=="nauvis", "Routes currently support Nauvis only.")
  assert(type(x)=="number" and type(y)=="number" and x==x and y==y
    and math.abs(x)<1000000 and math.abs(y)<1000000, "Supply finite resource coordinates.")
  quantity=quantity or 1
  assert(type(quantity)=="number" and quantity==math.floor(quantity) and quantity>=1 and quantity<=1000,
    "Quantity must be an integer from 1 to 1000.")
  assert(distance(actor.position,{x=x,y=y})<=64, "Target must be within 64 tiles of the character.")
  local count=0
  for _,request in pairs(storage.route_requests) do
    count=count+1
    assert(request.actor~=actor,"This character already has a pending route; wait for its result.")
  end
  assert(count<8,"Eight routes are already pending; wait for a result.")
  local found=actor.surface.find_entities_filtered{type="resource",position={x=x,y=y},radius=0.125}
  assert(#found==1,"Choose the exact center of one resource tile from the survey.")
  local resource=found[1]
  local mining=resource.prototype.mineable_properties
  assert(minerals[resource.name] and resource.minable and not resource.prototype.infinite_resource
    and not mining.required_fluid and #mining.products==1, "Only finite, hand-mineable base minerals are supported.")
  local product=mining.products[1]
  assert(product.name==resource.name and product.amount==1 and not product.amount_min and not product.amount_max
    and (not product.probability or product.probability==1)
    and (not product.independent_probability or product.independent_probability==1)
    and (not product.shared_probability or (product.shared_probability.min==0 and product.shared_probability.max==1)),
    "Mining must deterministically yield one item per cycle.")
  assert(resource.amount>=quantity,"The tile no longer holds the requested quantity; survey again.")
  assert(actor.get_main_inventory().can_insert{name=product.name,count=quantity},"Make inventory space for the requested minerals first.")
  -- Reject targets whose cursor position would select an obstacle above the ore.
  for _,e in pairs(actor.surface.find_entities_filtered{position=resource.position}) do
    assert(e==actor or e.type=="resource" or (not e.prototype.selectable_in_game and not e.prototype.collision_mask.layers.player),
      "The mineral is covered by an obstacle; clear it and survey again.")
  end
  local reach=actor.resource_reach_distance
  assert(reach>0.5 and reach<=32,"Unsupported character resource reach.")
  storage.route_sequence=(storage.route_sequence or 0)+1
  local box=actor.prototype.collision_box
  local inflated={{box.left_top.x-margin,box.left_top.y-margin},{box.right_bottom.x+margin,box.right_bottom.y+margin}}
  -- Our 2.1.16 wall/water scenario returned a water-crossing path with the raw
  -- character tile-transition mask. Explicit water blocking makes the search conservative;
  -- check_path still verifies the result against the real character mask.
  local path_mask={layers={},consider_tile_transitions=false}
  for name,value in pairs(actor.prototype.collision_mask.layers) do path_mask.layers[name]=value end
  path_mask.layers.water_tile=true
  local record={route_schema_version=1,source="factorio-native-pathfinder",
    exporter={name="blueprint-gen-observer",version=script.active_mods["blueprint-gen-observer"]},
    factorio_version=script.active_mods.base,active_mods=script.active_mods,
    sequence=storage.route_sequence,requested_tick=game.tick,generation=generation,
    surface_index=actor.surface.index,surface_name=actor.surface.name,map_seed=actor.surface.map_gen_settings.seed,
    force_index=actor.force.index,start=actor.position,
    actor={id=tostring(actor.unit_number),prototype=actor.name,resource_reach_distance=reach,
      collision_box=box,collision_mask=actor.prototype.collision_mask,clearance_margin=margin},
    target={id=resource.name..":"..resource.position.x..":"..resource.position.y,prototype=resource.name,
      item=product.name,position=resource.position,quantity=quantity,amount=resource.amount},
    goal_radius=reach-0.5,
    pathfinder_collision_mask=path_mask,
    constraints={can_open_gates=false,allow_destroy_friendly_entities=false,allow_paths_through_own_entities=false,
      cache=false,max_path_length=256,max_waypoints=2048},
    note="Native path under the captured configuration. No walking or mining was executed. Request again after changes."}
  local request={actor=actor,resource=resource,record=record,deadline=game.tick+600}
  if distance(actor.position,resource.position)<=record.goal_radius and actor.can_reach_entity(resource) then
    record.source="factorio-current-reach-check"
    record.path_validation={method="current-reach",clear=true}
    return write(request,"ready",{},{{position=actor.position,needs_destroy_to_reach=false}},generation)
  end
  local id=actor.surface.request_path{bounding_box=inflated,collision_mask=path_mask,
    start=actor.position,goal=resource.position,force=actor.force,radius=record.goal_radius,
    entity_to_ignore=actor,can_open_gates=false,max_gap_size=0,path_resolution_modifier=1,
    pathfind_flags={allow_destroy_friendly_entities=false,allow_paths_through_own_entities=false,cache=false,
      prefer_straight_paths=true}}
  record.request_id=id
  storage.route_requests[id]=request
  tell(actor,"Advisor is finding a walking approach. Stay still until the route is written.")
  return {request_id=id,sequence=record.sequence}
end

function M.finished(event,generation)
  local request=storage.route_requests[event.id]
  if not request then return end
  storage.route_requests[event.id]=nil
  local reasons=validate_end(request,generation)
  if #reasons>0 then return write(request,"invalidated",reasons,nil,generation) end
  if event.try_again_later then return write(request,"retry",{"native pathfinder was busy"},nil,generation) end
  if not event.path or #event.path==0 then return write(request,"no_path",{"no path found under these movement constraints"},nil,generation) end
  local path=event.path
  if distance(path[1].position,request.record.start)>0.001 then
    table.insert(path,1,{position=request.record.start,needs_destroy_to_reach=false})
  end
  local length=0
  for i,point in ipairs(path) do
    if point.needs_destroy_to_reach then reasons[#reasons+1]="path requires destroying an entity" end
    if i>1 then length=length+distance(path[i-1].position,point.position) end
  end
  if #path>2048 or length>256 then reasons[#reasons+1]="path exceeds the bounded route limits" end
  if distance(path[#path].position,request.record.target.position)>request.record.goal_radius+0.001 then
    reasons[#reasons+1]="path endpoint is outside the conservative mining radius"
  end
  if #reasons>0 then return write(request,"invalidated",reasons,nil,generation) end
  local clear,reason=check_path(request,path)
  if not clear then return write(request,"invalidated",{reason},nil,generation) end
  request.record.path_validation={method="swept-character-box",max_segment_length=0.125,clear=true}
  return write(request,"ready",{},path,generation)
end

function M.tick(generation)
  for id,request in pairs(storage.route_requests) do
    if game.tick>=request.deadline then
      write(request,"retry",{"path request timed out after 600 ticks"},nil,generation)
      storage.route_requests[id]=nil
    end
  end
end

return M

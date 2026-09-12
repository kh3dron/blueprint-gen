-- Find a reachable standing point for a declared build, without changing terrain.
-- The path validation mirrors live.lua; only goal selection and retries differ.
local M={}
local function distance(a,b) return ((a.x-b.x)^2+(a.y-b.y)^2)^.5 end
local function position(p) return {x=p.x,y=p.y} end
local function actor_mask(actor)
  local mask={layers={}}
  for k,v in pairs(actor.prototype.collision_mask) do if k~="layers" then mask[k]=v end end
  for k,v in pairs(actor.prototype.collision_mask.layers) do mask.layers[k]=v end
  return mask
end
local function terrain_layers(actor)
  local layers=actor_mask(actor).layers
  -- water_tile is a building-placement layer, also present on walkable belts.
  -- Check it only against tiles; adding it to an entity mask creates belt walls.
  layers.water_tile=true
  return layers
end
local function point_clear(actor,p,padding)
  padding=padding or .25
  local box=actor.prototype.collision_box
  local area={{p.x+box.left_top.x-padding,p.y+box.left_top.y-padding},
    {p.x+box.right_bottom.x+padding,p.y+box.right_bottom.y+padding}}
  if #actor.surface.find_tiles_filtered{area=area,collision_mask=terrain_layers(actor),limit=1}>0 then return false end
  for _,e in pairs(actor.surface.find_entities_filtered{area=area,collision_mask=actor_mask(actor).layers}) do
    if e~=actor then return false end
  end
  -- Belts remain traversable along the path, but can move an idle character.
  -- Reserve padded standing room so a build or later measurement stays still.
  local belt_padding=math.max(padding,.1)
  local belt_area={{p.x+box.left_top.x-belt_padding,p.y+box.left_top.y-belt_padding},
    {p.x+box.right_bottom.x+belt_padding,p.y+box.right_bottom.y+belt_padding}}
  if #actor.surface.find_entities_filtered{area=belt_area,
    type={"transport-belt","underground-belt","splitter"}}>0 then return false end
  return true
end
local function outside_build(spec,p)
  local box=prototypes.entity[spec.name].collision_box
  local half_x=math.max(math.abs(box.left_top.x),math.abs(box.right_bottom.x))+.4
  local half_y=math.max(math.abs(box.left_top.y),math.abs(box.right_bottom.y))+.4
  -- Current science entities have square footprints. Swap extents as well so
  -- the generic approach remains correct for a rectangular rotated prototype.
  if spec.direction==4 or spec.direction==12 then half_x,half_y=half_y,half_x end
  return math.abs(p.x-spec.position.x)>=half_x or math.abs(p.y-spec.position.y)>=half_y
end
local function valid_endpoint(job,p,tolerance,padding)
  return distance(p,job.science_walk.spec.position)<=job.science_walk.reach+(tolerance or 0)
    and outside_build(job.science_walk.spec,p) and point_clear(storage.actor,p,padding)
end
local function checked_path(path,start)
  assert(path and #path>0 and #path<=2048,"no bounded native path")
  if distance(path[1].position,start)>.001 then table.insert(path,1,{position=position(start),needs_destroy_to_reach=false}) end
  local actor,box=storage.actor,storage.actor.prototype.collision_box
  local layers=actor_mask(actor).layers
  local tiles=terrain_layers(actor)
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
        assert(#actor.surface.find_tiles_filtered{area=area,collision_mask=tiles,limit=1}==0,"path crosses terrain")
        for _,e in pairs(actor.surface.find_entities_filtered{area=area,collision_mask=layers}) do
          assert(e==actor,"path intersects entity")
        end
      end
    end
  end
  return path
end
local function request_next(job)
  local walk=job.science_walk
  walk.candidate=walk.candidate+1
  local candidate=walk.candidates[walk.candidate]
  if not candidate then
    job.science_walk_error="no safe native path to any bounded science build approach"
    return
  end
  local actor,box=storage.actor,storage.actor.prototype.collision_box
  -- A failed candidate can consume ticks while the actor stands on an old
  -- belt. Every retry starts at the current native position.
  job.start=position(actor.position)
  job.request_id=actor.surface.request_path{
    bounding_box={{box.left_top.x-.25,box.left_top.y-.25},{box.right_bottom.x+.25,box.right_bottom.y+.25}},
    collision_mask=actor_mask(actor),
    start=job.start,goal=candidate.position,force=actor.force,radius=candidate.radius,
    entity_to_ignore=actor,can_open_gates=false,max_gap_size=0,path_resolution_modifier=2,
    pathfind_flags={allow_destroy_friendly_entities=false,allow_paths_through_own_entities=false,
      cache=false,prefer_straight_paths=true}}
  walk.attempts[#walk.attempts+1]={id=job.request_id,start=position(job.start),goal=candidate.position,radius=candidate.radius}
end
function M.begin(args,job)
  local actor=storage.actor
  local spec=assert(args.spec,"science walk requires a placement spec")
  assert(type(spec.address)=="string" and string.sub(spec.address,1,8)=="science.","science walk requires a science address")
  assert(prototypes.entity[spec.name] and prototypes.entity[spec.name].collision_box,"unknown science placement prototype")
  assert(spec.direction==0 or spec.direction==4 or spec.direction==8 or spec.direction==12,"invalid build direction")
  assert(spec.position and type(spec.position.x)=="number" and type(spec.position.y)=="number","invalid build position")
  assert(distance(actor.position,spec.position)<=64,"science walk target beyond bounded range")
  local reach=math.min(actor.build_distance,actor.reach_distance)-1.5
  assert(reach>1,"science build reach is too small")
  job.start=position(actor.position)
  job.science_walk={spec={address=spec.address,name=spec.name,position=position(spec.position),direction=spec.direction},
    reach=reach,candidate=0,attempts={},candidates={{position=position(spec.position),radius=reach}}}
  if valid_endpoint(job,job.start) then
    job.path={{position=position(job.start),needs_destroy_to_reach=false}};job.waypoint=2
    return
  end
  local alternatives={}
  for _,radius in ipairs({reach-.5,reach*.65}) do
    for angle=0,15 do
      local theta=angle*math.pi/8
      local p={x=spec.position.x+radius*math.cos(theta),y=spec.position.y+radius*math.sin(theta)}
      if outside_build(spec,p) and point_clear(actor,p) then
        alternatives[#alternatives+1]={position=p,radius=.25}
      end
    end
  end
  table.sort(alternatives,function(a,b)
    local da,db=distance(a.position,job.start),distance(b.position,job.start)
    if da~=db then return da<db end
    if a.position.x~=b.position.x then return a.position.x<b.position.x end
    return a.position.y<b.position.y
  end)
  for _,candidate in ipairs(alternatives) do job.science_walk.candidates[#job.science_walk.candidates+1]=candidate end
  request_next(job)
end
function M.on_path_finished(event)
  local job=storage.job
  if not job or job.request.op~="walk_science" or event.id~=job.request_id then return false end
  job.request_id=nil
  local attempt=job.science_walk.attempts[#job.science_walk.attempts]
  local actor=storage.actor
  local current=position(actor.position)
  local drift=distance(current,job.start)
  local controlled_movement=actor.walking_state.walking or actor.mining_state.mining
  attempt.drift_tiles=drift
  local ok,result=pcall(function()
    assert(not event.try_again_later,"native pathfinder busy")
    assert(not controlled_movement,"player acted during science pathfinding")
    assert(drift<=2,"passive pathfinding drift exceeds two tiles")
    -- Reconnecting the actual current position to the returned native path
    -- goes through the same swept collision and total-length checks.
    local path=checked_path(event.path,current)
    assert(valid_endpoint(job,path[#path].position),"native path ends outside a safe build approach")
    return path
  end)
  attempt.tick=game.tick
  if ok then
    attempt.accepted=true;job.path=result;job.waypoint=2
  else
    attempt.accepted=false;attempt.reason=tostring(result)
    if controlled_movement or drift>2 then
      job.science_walk_error="unsafe movement during science pathfinding"
    else request_next(job) end
  end
  return true
end
function M.tick(job,walk)
  if job.science_walk_error then
    local counts,summary={},{}
    for _,attempt in ipairs(job.science_walk.attempts) do
      if attempt.reason then
        local reason=attempt.reason:match(":%d+: (.*)") or attempt.reason
        counts[reason]=(counts[reason] or 0)+1
      end
    end
    for reason,count in pairs(counts) do summary[#summary+1]=count.."x "..reason end
    table.sort(summary)
    error(job.science_walk_error.." ("..#job.science_walk.attempts.." attempts; "..table.concat(summary,"; ")..")")
  end
  if job.path and walk(job) then
    -- The shared walker stops within .12 tiles of its waypoint. The requested
    -- radius leaves .5 tiles inside native build reach to cover that tolerance.
    assert(valid_endpoint(job,storage.actor.position,.15,0),"science walking did not reach a safe build position")
    return {position=position(storage.actor.position),path=job.path,address=job.science_walk.spec.address,
      target=job.science_walk.spec.position,build_reach=job.science_walk.reach,attempts=job.science_walk.attempts}
  end
end
return M

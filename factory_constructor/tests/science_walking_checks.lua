-- Bounded path retries and validation only; no Factorio process is started.
local root=assert(arg[1],"repository root argument is required")..'/'
local function fails(fn,message)
  local ok,err=pcall(fn);assert(not ok and tostring(err):find(message,1,true),tostring(err))
end
local requested,obstacle={},nil
local standing_belt_x
local belt={name='transport-belt'}
local box={left_top={x=-.2,y=-.2},right_bottom={x=.2,y=.2}}
local actor={position={x=20,y=0},build_distance=10,reach_distance=10,force={},
  walking_state={walking=false},mining_state={mining=false},
  prototype={collision_box=box,collision_mask={layers={player=true,is_object=true,train=true},consider_tile_transitions=true}}}
actor.surface={find_tiles_filtered=function(q)assert(q.collision_mask.water_tile);return {}end,
  -- Native Factorio 2.1.17 evidence: a belt is walkable with the character's
  -- layers, but falsely matches if the building water_tile layer is added.
  find_entities_filtered=function(q)
    if q.type then
      return standing_belt_x and q.area[1][1]<=standing_belt_x and q.area[2][1]>=standing_belt_x and {belt} or {}
    end
    return obstacle and {obstacle} or q.collision_mask.water_tile and {belt} or {}
  end,
  request_path=function(args)requested[#requested+1]=args;return #requested end}
storage={actor=actor};game={tick=100}
prototypes={entity={['small-electric-pole']={collision_box=box}}}
local walking=dofile(root..'factory_constructor/integration/science_walking.lua')
local spec={address='science.pole',name='small-electric-pole',position={x=0,y=0},direction=0}
local function begin()
  local job={request={op='walk_science'},started=game.tick};storage.job=job
  walking.begin({spec=spec},job);return job
end
local job=begin()
assert(requested[1].radius==8.5 and requested[1].goal.x==0)
assert(requested[1].max_gap_size==0 and requested[1].path_resolution_modifier==2)
assert(requested[1].collision_mask.consider_tile_transitions==true)
assert(requested[1].collision_mask.layers.water_tile==nil and requested[1].collision_mask.layers.train)
assert(not requested[1].pathfind_flags.allow_destroy_friendly_entities)
assert(not requested[1].pathfind_flags.allow_paths_through_own_entities)
assert(not walking.on_path_finished{id=999,path={}})
assert(walking.on_path_finished{id=job.request_id})
assert(#requested==2 and requested[2].radius==.25 and #job.science_walk.attempts==2)
local target=requested[2].goal
assert(walking.on_path_finished{id=job.request_id,path={{position=actor.position},{position=target}}})
local result=walking.tick(job,function()actor.position={x=target.x+.1,y=target.y};return true end)
assert(result.address==spec.address and #result.attempts==2 and result.attempts[2].accepted)
print('Build-reach radius, alternate goal, and walker tolerance checks passed')

actor.position={x=20,y=0};job=begin()
assert(walking.on_path_finished{id=job.request_id,path={{position={x=8,y=0},needs_destroy_to_reach=true}}})
assert(job.science_walk.attempts[1].reason:find('destruction',1,true))
assert(walking.on_path_finished{id=job.request_id,path={{position={x=300,y=0}}}})
assert(job.science_walk.attempts[2].reason:find('path too long',1,true))
obstacle={}
assert(walking.on_path_finished{id=job.request_id,path={{position={x=8,y=0}}}})
assert(job.science_walk.attempts[3].reason:find('intersects entity',1,true))
obstacle=nil
while job.request_id do assert(walking.on_path_finished{id=job.request_id}) end
assert(#job.science_walk.attempts<=33)
fails(function()walking.tick(job,function()end)end,'no safe native path')
fails(function()walking.tick(job,function()end)end,'attempts;')
fails(function()walking.tick(job,function()end)end,'1x path too long')
print('Destruction, collision, path-length, and bounded retry refusal checks passed')

actor.position={x=0,y=0};job=begin()
assert(job.request_id and not job.path)
assert(walking.on_path_finished{id=job.request_id,path={{position={x=0,y=0}}}})
assert(job.science_walk.attempts[1].reason:find('safe build approach',1,true))
actor.position={x=65,y=0}
fails(begin,'beyond bounded range')
print('Occupied build footprint and distant goal refusal checks passed')

-- A belt under the desired standing point invalidates only the endpoint.
actor.position={x=20,y=0};job=begin();standing_belt_x=8
assert(walking.on_path_finished{id=job.request_id,path={{position={x=8,y=0}}}})
assert(job.science_walk.attempts[1].reason:find('safe build approach',1,true))
standing_belt_x=nil
local pending_start=requested[job.request_id].start
actor.position={x=pending_start.x+.03125,y=pending_start.y}
assert(walking.on_path_finished{id=job.request_id,path={{position=pending_start},{position={x=8,y=0}}}})
assert(job.path[1].position.x==actor.position.x and job.science_walk.attempts[2].drift_tiles==.03125)
local accepted=walking.tick(job,function()actor.position={x=8,y=0};return true end)
assert(accepted.position.x==8)

-- Rejected paths also re-anchor the next request, and excessive drift refuses.
actor.position={x=20,y=0};job=begin();actor.position={x=20.5,y=0}
assert(walking.on_path_finished{id=job.request_id})
assert(requested[job.request_id].start.x==20.5)
actor.position={x=23,y=0}
assert(walking.on_path_finished{id=job.request_id,path={{position={x=8,y=0}}}})
fails(function()walking.tick(job,function()end)end,'drift exceeds two tiles')
print('Off-belt endpoints, passive drift re-anchoring, and retry start checks passed')

local delegated=0
local previous=function()delegated=delegated+1 end
local handler
defines={events={on_script_path_request_finished=1}}
script={get_event_handler=function()return previous end,on_event=function(_,fn)handler=fn end}
package.loaded.feed_control=true;package.loaded.science_walking=walking;package.loaded.extension={}
dofile(root..'factory_constructor/integration/science_control.lua')
storage.job={request={op='walk_to'}};handler{id=999};assert(delegated==1)
actor.position={x=20,y=0};job=begin();handler{id=job.request_id}
assert(delegated==1 and #job.science_walk.attempts==2)
print('Legacy path handler delegation and science request isolation checks passed')

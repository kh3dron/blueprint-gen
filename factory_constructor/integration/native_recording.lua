-- Opt-in presentation capture. All game state is observed without changing it.
local M={}
local trace_path="constructor-video.jsonl"
local configured_once=false

local function number(value,name,minimum,maximum,integer)
  assert(type(value)=="number" and value==value and value>=minimum and value<=maximum
    and (not integer or value==math.floor(value)),"invalid recording "..name)
  return value
end

local function idle()
  assert(not storage.job and game.tick_paused,"recording control requires a paused idle boundary")
end

local function attached_player()
  local actor=storage.actor
  local player=storage.capture_player and game.get_player(storage.capture_player)
  assert(actor and actor.valid and player and player.connected and player.character==actor
    and actor.player==player,"recording requires the attached original player")
  assert(not storage.capture_enabled,"disable legacy recording before constructor recording")
  return player
end

local function build_count()
  local count=0
  for _ in pairs(storage.science_built or {}) do count=count+1 end
  return count
end

local function production(item)
  local actor=storage.actor
  local stats=actor.force.get_item_production_statistics(actor.surface)
  return {science_produced=stats.get_input_count(item),
    copper_produced=stats.get_input_count("copper-plate"),
    iron_produced=stats.get_input_count("iron-plate"),
    coal_produced=stats.get_input_count("coal")}
end

local function capture()
  local recording=assert(storage.constructor_recording,"configure constructor recording first")
  assert(recording.enabled,"constructor recording is disabled")
  local player=attached_player()
  local settings=recording.settings
  local request=storage.job and storage.job.request or storage.last_action or {}
  local frame=recording.frame+1
  local path=string.format("constructor-video/frame-%06d.png",frame)
  local actor=storage.actor
  local row={frame=frame,tick=game.tick,image=path,
    position={x=actor.position.x,y=actor.position.y},
    op=request.op or "idle",label=request.label or settings.goal,
    program_node=request.program_node or "",
    added_builds=build_count()-recording.baseline_builds}
  for name,value in pairs(production(settings.item)) do
    row[name]=value-recording.baseline[name]
  end
  game.take_screenshot{by_player=player,player=player,surface=actor.surface,
    position=settings.camera,resolution=settings.resolution,zoom=settings.zoom,path=path,
    show_gui=false,show_entity_info=true,hide_clouds=true,hide_fog=true,
    daytime=0,force_render=true}
  -- A server-only trace avoids duplicate metadata from the graphical client.
  helpers.write_file(trace_path,helpers.table_to_json(row).."\n",true,0)
  recording.frame=frame
  return row
end

function M.configure(settings)
  idle();attached_player()
  assert(not configured_once,"constructor recording is already configured")
  assert(type(settings)=="table" and type(settings.camera)=="table"
    and type(settings.resolution)=="table","recording settings require a camera and resolution")
  assert(type(settings.goal)=="string" and #settings.goal>0,"recording requires a goal label")
  assert(type(settings.item)=="string" and prototypes.item[settings.item],"invalid recording item")
  local camera={x=number(settings.camera.x,"camera x",-1000000,1000000),
    y=number(settings.camera.y,"camera y",-1000000,1000000)}
  local configured={camera=camera,zoom=number(settings.zoom,"zoom",.05,4),
    resolution={number(settings.resolution[1],"width",1,4096,true),
      number(settings.resolution[2],"height",1,4096,true)},
    interval_ticks=number(settings.interval_ticks or 300,"interval_ticks",60,3600,true),
    goal=settings.goal,item=settings.item,target=number(settings.target,"target",0,1000000),
    total_builds=number(settings.total_builds,"total_builds",0,1000000,true)}
  storage.constructor_recording={enabled=true,frame=0,settings=configured,
    baseline=production(configured.item),baseline_builds=build_count(),configured_tick=game.tick}
  helpers.write_file(trace_path,"",false,0)
  configured_once=true
  return {enabled=true,frame=0,tick=game.tick,settings=configured}
end

function M.capture()
  idle()
  return capture()
end

function M.disable()
  idle()
  local recording=storage.constructor_recording
  if recording then recording.enabled=false end
  return {enabled=false,frame=recording and recording.frame or 0}
end

local previous=script.get_event_handler(defines.events.on_tick)
script.on_event(defines.events.on_tick,function(event)
  if previous then previous(event) end
  local recording,job=storage.constructor_recording,storage.job
  if recording and recording.enabled and job and job.request.op=="wait_science" then
    local elapsed=game.tick-job.started
    if elapsed>0 and elapsed%recording.settings.interval_ticks==0 then capture() end
  end
end)
remote.add_interface("constructor-recording",M)
return M

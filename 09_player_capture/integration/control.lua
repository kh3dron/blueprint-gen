-- Isolated player/capture extension. The headless controller remains unchanged.
require("live")

local function contents(actor)
  local out={}
  for _,s in pairs(actor.get_main_inventory().get_contents()) do
    assert(s.quality=="normal");out[s.name]=(out[s.name] or 0)+s.count
  end
  return out
end
local function attach(event)
  local player=game.get_player(event.player_index)
  assert(not storage.capture_player or storage.capture_player==player.index,"only one experiment player is supported")
  assert(not storage.job,"attach at an idle boundary")
  local actor=storage.actor
  local before={character_id=tostring(actor.unit_number),position=actor.position,inventory=contents(actor)}
  local extra=player.character
  player.set_controller{type=defines.controllers.character,character=actor}
  if extra and extra.valid and extra~=actor then extra.destroy() end
  assert(player.character==actor and actor.player==player,"player did not attach")
  player.zoom=.8
  storage.capture_player=player.index
  storage.attachment={before=before,after={character_id=tostring(actor.unit_number),position=actor.position,
    inventory=contents(actor)},player_index=player.index,cheat_mode=player.cheat_mode,tick=game.tick}
  helpers.write_file("player-attachment.json",helpers.table_to_json(storage.attachment),false)
end
script.on_event(defines.events.on_player_created,attach)

script.on_event(defines.events.on_player_crafted_item,function(event)
  if event.player_index~=storage.capture_player then return end
  helpers.write_file("player-crafts.jsonl",helpers.table_to_json{tick=game.tick,player_index=event.player_index,
    recipe=event.recipe.name,item=event.item_stack.name,count=event.item_stack.count}.."\n",true)
end)

local function capture(event)
  if not storage.capture_enabled then return end
  local player=game.get_player(storage.capture_player)
  assert(player and player.connected and player.character==storage.actor,"capture player disconnected")
  storage.native_frame=(storage.native_frame or 0)+1
  local path=string.format("native/frame-%06d.png",storage.native_frame)
  local result=remote.call("opening-executor","call",{op="status"})
  assert(result.ok)
  local state=result.value
  state.event=event;state.frame=storage.native_frame;state.image=path
  state.action=storage.job and storage.job.request or storage.last_action
  helpers.write_file("native-trace.jsonl",helpers.table_to_json(state).."\n",true)
  game.take_screenshot{by_player=player,player=player,surface=storage.actor.surface,
    position=storage.actor.position,resolution={960,640},zoom=.8,path=path,
    show_gui=false,show_entity_info=true,hide_clouds=true,hide_fog=true,daytime=0,force_render=true}
  return state
end
local live_tick=script.get_event_handler(defines.events.on_tick)
script.on_event(defines.events.on_tick,function(event)
  local starting=storage.job and storage.job.started==game.tick-1
  live_tick(event)
  if storage.capture_enabled and (starting or game.tick%60==0 or game.tick_paused) then
    capture(game.tick_paused and "boundary" or starting and "start" or "sample")
  end
end)
remote.add_interface("player-capture",{
  status=function()
    local p=storage.capture_player and game.get_player(storage.capture_player)
    return {attached=p and p.connected and p.character==storage.actor or false,attachment=storage.attachment}
  end,
  enable=function()
    assert(storage.capture_player and not storage.job and game.tick_paused,"enable after player attachment")
    storage.capture_enabled=true
    return capture("initial")
  end,
  capture=function() assert(not storage.job and game.tick_paused);return capture("manual") end
})

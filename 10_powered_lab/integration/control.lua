require("capture")
script.on_event(defines.events.on_built_entity,function(event)
  storage.player_build_events=storage.player_build_events or {}
  storage.player_build_events[#storage.player_build_events+1]={tick=game.tick,player_index=event.player_index,
    id=tostring(event.entity.unit_number),name=event.entity.name,position=event.entity.position}
end)

require("power_control")
script.on_event(defines.events.on_player_mined_entity,function(event)
  if event.entity.type~="tree" then return end
  storage.tree_events=storage.tree_events or {}
  local products={}
  for _,s in pairs(event.buffer.get_contents()) do products[s.name]=(products[s.name] or 0)+s.count end
  storage.tree_events[#storage.tree_events+1]={tick=game.tick,player_index=event.player_index,
    id=event.entity.unit_number and tostring(event.entity.unit_number) or
      event.entity.name..":"..event.entity.position.x..":"..event.entity.position.y,
    name=event.entity.name,position=event.entity.position,products=products}
end)

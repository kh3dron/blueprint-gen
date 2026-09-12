require("feed_control")
local walking=require("science_walking")
local previous=script.get_event_handler(defines.events.on_script_path_request_finished)
script.on_event(defines.events.on_script_path_request_finished,function(event)
  local job=storage.job
  if job and job.request.op=="walk_science" then
    local ok,err=pcall(walking.on_path_finished,event)
    if not ok then job.science_walk_error=tostring(err) end
  elseif previous then previous(event) end
end)

-- Action receipts and explicit observations retain the complete evidence. Avoid
-- repeating the whole connected factory twice (server/client) at every boundary.
require("extension").trace=function()
  return {tick=game.tick,revision=storage.revision,position=storage.actor.position,
    paused=game.tick_paused,trace_kind="constructor-boundary"}
end

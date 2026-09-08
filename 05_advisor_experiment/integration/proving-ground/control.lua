-- Isolated proving-ground scenario, not part of the read-only observer mod.
local ground=require("ground")
script.on_init(ground.init)
script.on_event(defines.events.on_chunk_generated,ground.chunk_generated)
script.on_event(defines.events.on_player_created,ground.player_created)

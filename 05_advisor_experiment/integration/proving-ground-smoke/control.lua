local ground=require("ground")
local config=require("config")
script.on_event(defines.events.on_chunk_generated,ground.chunk_generated)
script.on_init(function()
  ground.init()
  local surface=game.surfaces.nauvis
  storage.actor=assert(surface.create_entity{name="character",position=config.spawn,force="player"})
  ground.give_inventory(storage.actor)
end)
script.on_event(defines.events.on_tick,function(event)
  if event.tick==1 then
    -- Exercise ordinary runtime chunk events, beyond the initial prepared area.
    game.surfaces.nauvis.request_to_generate_chunks({1024,0},1)
    game.surfaces.nauvis.force_generate_chunk_requests()
  elseif event.tick==120 then
    local surface=game.surfaces.nauvis
    local totals,tiles={},{ }
    for _,entity in pairs(surface.find_entities_filtered{type="resource"}) do
      totals[entity.name]=(totals[entity.name] or 0)+entity.amount
      tiles[entity.name]=(tiles[entity.name] or 0)+1
    end
    local first=config.patches[1]
    local ore=surface.find_entities_filtered{type="resource",position={first.x+.5,first.y+.5},radius=.1}[1]
    assert(ore,"missing configured ore: "..helpers.table_to_json{totals=totals,tiles=tiles})
    ore.amount=ore.amount-3
    local chunk={x=math.floor(first.x/32),y=math.floor(first.y/32)}
    ground.chunk_generated{surface=surface,position=chunk,area={left_top={x=chunk.x*32,y=chunk.y*32},
      right_bottom={x=chunk.x*32+32,y=chunk.y*32+32}}}
    assert(ore.valid and ore.amount==first.amount-3,"revisiting a chunk refilled resources")
    assert(surface.get_tile(1024,0).name=="grass-1","distant terrain is not flat")
    assert(#surface.find_entities_filtered{area={{1008,-16},{1040,16}},type={"resource","tree","cliff"}}==0)
    local researched={}
    for name,tech in pairs(game.forces.player.technologies) do if tech.researched then researched[#researched+1]=name end end
    helpers.write_file("ground-results.json",helpers.table_to_json{
      factorio_version=script.active_mods.base,active_mods=script.active_mods,config=config,
      resource_totals_before_depletion=totals,resource_tile_counts=tiles,
      tree_count=#surface.find_entities_filtered{type="tree"},
      water_count=surface.count_tiles_filtered{name="water"},
      far_tile=surface.get_tile(1024,0).name,resource_not_refilled=true,
      inventory=storage.actor.get_main_inventory().get_contents(),researched=researched,
      width=surface.map_gen_settings.width,height=surface.map_gen_settings.height},false)
    remote.call("blueprint-gen-observer","survey_area",surface.index,game.forces.player.index,
      config.spawn[1],config.spawn[2],64)
  end
end)

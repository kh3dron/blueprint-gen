-- Test-only fixtures, staged exclusively in a disposable game profile.
script.on_init(function()
  local surface, force = game.surfaces[1], game.forces.player
  surface.request_to_generate_chunks({0, 0}, 2)
  surface.force_generate_chunk_requests()
  for _, e in pairs(surface.find_entities_filtered{area = {{-40,-40},{40,40}}}) do e.destroy() end
  local tiles = {}
  for x=-40,40 do for y=-40,40 do tiles[#tiles+1]={name="grass-1",position={x,y}} end end
  for y=-12,6 do tiles[#tiles+1]={name="water",position={0,y}} end
  surface.set_tiles(tiles)
  local function resource(name,x,y,amount)
    return assert(surface.create_entity{name=name,position={x+.5,y+.5},amount=amount})
  end
  resource("iron-ore",-12,0,25)
  resource("iron-ore",-11,0,30)
  resource("iron-ore",10,0,200)
  resource("coal",-8,-4,10)
  resource("stone",-14,-12,5)
  resource("uranium-ore",14,8,100)
  storage.blocked = resource("iron-ore",-8,0,10000)
  surface.create_entity{name="stone-wall",position={-8,0},force=force}
  resource("coal",5,-5,200)
  storage.drill = surface.create_entity{name="burner-mining-drill",position={5,-5},force=force}
  for _, name in ipairs({"steam-power","electronics","automation-science-pack","automation"}) do
    force.technologies[name].researched=true
  end
  storage.assembler=surface.create_entity{name="assembling-machine-1",position={-8,4},force=force}
  storage.assembler.set_recipe("iron-gear-wheel")
  storage.chest=surface.create_entity{name="wooden-chest",position={-8,1},force=force}
  storage.chest.insert{name="iron-plate",count=30}
  storage.inserter=surface.create_entity{name="inserter",position={-8,2},direction=defines.direction.north,force=force}
  storage.pole1=surface.create_entity{name="small-electric-pole",position={-6,1},force=force}
  storage.pole2=surface.create_entity{name="small-electric-pole",position={-4,-4},force=force}
  storage.isolated=surface.create_entity{name="small-electric-pole",position={11,-12},force=force}
  local power=surface.create_entity{name="electric-energy-interface",position={-4,-6},force=force}
  power.electric_buffer_size=1000000000
  power.power_production=10000000
  power.energy=1000000000
  surface.create_entity{name="stone-furnace",position={-18,3},force=force}
  surface.create_entity{name="entity-ghost",inner_name="assembling-machine-1",position={-18,9},force=force}
  storage.surface,storage.force=surface.index,force.index
end)

script.on_event(defines.events.on_tick,function(event)
  if event.tick==120 then
    remote.call("blueprint-gen-observer","survey_area",storage.surface,storage.force,-8,-8,24)
    local facts={inserter_id=tostring(storage.inserter.unit_number),chest_id=tostring(storage.chest.unit_number),
      assembler_id=tostring(storage.assembler.unit_number),pole1_id=tostring(storage.pole1.unit_number),
      pole2_id=tostring(storage.pole2.unit_number),isolated_id=tostring(storage.isolated.unit_number),
      blocked_resource_position=storage.blocked.position,drill_id=tostring(storage.drill.unit_number)}
    helpers.write_file("survey-smoke-results.json",helpers.table_to_json(facts),false)
  elseif event.tick==121 then
    storage.chest.destroy()
  elseif event.tick==122 then
    remote.call("blueprint-gen-observer","survey_area",storage.surface,storage.force,-8,-8,24)
  end
end)

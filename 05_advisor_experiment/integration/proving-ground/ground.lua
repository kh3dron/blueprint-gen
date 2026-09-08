-- Fresh scenario terrain only. Chunks are initialized once; resources never refill.
local config=require("config")
local M={}
local function inside(x,y,r)
  return x>=r.x and x<r.x+r.width and y>=r.y and y<r.y+r.height
end

function M.chunk_generated(event)
  if not storage.ground_ready or event.surface.name~="nauvis" then return end
  local key=event.position.x..":"..event.position.y
  if storage.ground_chunks[key] then return end
  storage.ground_chunks[key]=true
  local surface,area=event.surface,event.area
  for _,entity in pairs(surface.find_entities_filtered{area=area}) do
    -- Area queries can include a neighboring chunk's tree collision box.
    -- Only clear entities whose centers belong to this newly initialized chunk.
    local p=entity.position
    if p.x>=area.left_top.x and p.x<area.right_bottom.x and p.y>=area.left_top.y and p.y<area.right_bottom.y
      and (entity.force.name=="neutral" or entity.force.name=="enemy") then entity.destroy() end
  end
  surface.destroy_decoratives{area=area}
  local tiles={}
  for x=area.left_top.x,area.right_bottom.x-1 do
    for y=area.left_top.y,area.right_bottom.y-1 do
      local name="grass-1"
      for _,r in ipairs(config.water) do if inside(x,y,r) then name="water" end end
      tiles[#tiles+1]={name=name,position={x,y}}
    end
  end
  surface.set_tiles(tiles,true,false,false,false)
  for _,r in ipairs(config.patches) do
    for x=math.max(r.x,area.left_top.x),math.min(r.x+r.width,area.right_bottom.x)-1 do
      for y=math.max(r.y,area.left_top.y),math.min(r.y+r.height,area.right_bottom.y)-1 do
        assert(surface.create_entity{name=r.item,position={x+.5,y+.5},amount=r.amount})
      end
    end
  end
  for _,p in ipairs(config.trees) do
    if p.x>=area.left_top.x and p.x<area.right_bottom.x and p.y>=area.left_top.y and p.y<area.right_bottom.y then
      assert(surface.create_entity{name="tree-01",position={p.x+.5,p.y+.5}})
    end
  end
end

function M.init()
  storage.ground_chunks={}
  local surface=game.surfaces.nauvis
  surface.map_gen_settings={seed=config.seed,width=0,height=0,water=0,peaceful_mode=true,
    property_expression_names={elevation="100"},
    autoplace_settings={entity={treat_missing_as_default=false,settings={}},
      decorative={treat_missing_as_default=false,settings={}}},
    cliff_settings={cliff_elevation_interval=0,cliff_elevation_0=0}}
  storage.ground_ready=true
  surface.request_to_generate_chunks(config.spawn,3)
  surface.force_generate_chunk_requests()
  -- Initial generation can precede event delivery during scenario conversion.
  -- Initialize existing chunks explicitly; the once-only ledger also handles later events.
  for chunk in surface.get_chunks() do
    M.chunk_generated{surface=surface,position=chunk,area={
      left_top={x=chunk.x*32,y=chunk.y*32},right_bottom={x=chunk.x*32+32,y=chunk.y*32+32}}}
  end
  game.forces.player.set_spawn_position(config.spawn,surface)
end

function M.give_inventory(actor)
  for item,count in pairs(config.inventory) do
    assert(actor.insert{name=item,count=count}==count,"starter inventory did not fit")
  end
end

function M.player_created(event)
  local player=game.get_player(event.player_index)
  player.teleport(config.spawn,game.surfaces.nauvis)
  player.clear_items_inside()
  M.give_inventory(player)
  player.print("Proving ground: produce 10 red science per minute. Deposits are finite; terrain extends as explored.")
end

return M

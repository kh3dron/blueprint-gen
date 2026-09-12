-- Real cursor placement. Only transfers/site checks reuse the old test adapter.
local previous=require("transfers")
local M={site=previous.site,transfer=previous.transfer}
local allowed={['stone-furnace']=true,['offshore-pump']=true,boiler=true,['steam-engine']=true,
  pipe=true,['small-electric-pole']=true,lab=true}
local function distance(a,b) return ((a.x-b.x)^2+(a.y-b.y)^2)^.5 end
local function inventory(actor)
  local out={}
  for _,s in pairs(actor.get_main_inventory().get_contents()) do
    assert(s.quality=="normal");out[s.name]=(out[s.name] or 0)+s.count
  end
  return out
end
local function equal(a,b)
  for k,v in pairs(a) do if b[k]~=v then return false end end
  for k,v in pairs(b) do if a[k]~=v then return false end end
  return true
end
function M.place(actor,spec,extension)
  assert((allowed[spec.name] or (extension and extension.allowed[spec.name])) and not spec.recipe,"unsupported player placement")
  assert(type(spec.address)=="string" and #spec.address>0,"placement needs a stable address")
  assert(spec.direction==0 or spec.direction==4 or spec.direction==8 or spec.direction==12,"invalid direction")
  storage.power_built=storage.power_built or {}
  local built=extension and extension.built or (spec.name=="stone-furnace" and storage.built or storage.power_built)
  local prior=storage.built[spec.address] or storage.power_built[spec.address] or built[spec.address]
  if prior then
    assert(prior.valid and prior.name==spec.name and prior.direction==spec.direction
      and distance(prior.position,spec.position)<.001 and prior.force==actor.force,"declarative entity drift")
    return prior,false
  end
  local player=assert(actor.player,"placement requires an attached player")
  assert(player.connected and player.character==actor and not player.cheat_mode,"normal connected player required")
  assert(distance(actor.position,spec.position)<=math.min(actor.build_distance,actor.reach_distance)-1,"out_of_reach")
  assert(actor.force.recipes[spec.name].enabled,"missing_research")
  if spec.name=="stone-furnace" then local ok,why=M.site(actor,spec.position);assert(ok,why) end
  local inv,cursor=actor.get_main_inventory(),player.cursor_stack
  assert(not cursor.valid_for_read,"cursor must be empty")
  local slot=assert(inv.find_item_stack(spec.name),"missing_item")
  assert(slot.quality.name=="normal","unsupported item quality")
  local before=inventory(actor)
  assert(cursor.swap_stack(slot),"cursor transfer failed")
  local entity
  local ok,err=pcall(function()
    local params={position=spec.position,direction=spec.direction,build_mode=defines.build_mode.normal}
    assert(player.can_build_from_cursor(params),"cursor_build_blocked")
    player.build_from_cursor(params)
    entity=actor.surface.find_entity(spec.name,spec.position)
    assert(entity and entity.valid and entity.force==actor.force,"cursor build produced no entity")
  end)
  if cursor.valid_for_read then assert(cursor.swap_stack(slot),"cursor return failed") end
  assert(not cursor.valid_for_read,"cursor did not empty")
  if not ok then assert(equal(before,inventory(actor)),"failed build changed inventory");error(err) end
  local expected={};for k,v in pairs(before) do expected[k]=v end
  expected[spec.name]=expected[spec.name]-1;if expected[spec.name]==0 then expected[spec.name]=nil end
  assert(equal(expected,inventory(actor)),"cursor placement did not debit exactly one item")
  assert(entity.direction==spec.direction,"built direction differs")
  built[spec.address]=entity
  if spec.name=="stone-furnace" then storage.paid_furnaces=storage.paid_furnaces+1 end
  storage.cursor_placements=storage.cursor_placements or {}
  storage.cursor_placements[#storage.cursor_placements+1]={tick=game.tick,address=spec.address,
    id=tostring(entity.unit_number),name=entity.name,position=entity.position,direction=entity.direction,
    before=before,after=inventory(actor),player_index=player.index}
  return entity,true
end
return M

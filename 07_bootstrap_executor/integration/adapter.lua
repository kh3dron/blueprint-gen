-- Disposable test adapter, not LuaPlayer cursor placement. Never shipped in the observer.
local M={}
local function distance(a,b) return ((a.x-b.x)^2+(a.y-b.y)^2)^.5 end

function M.site(actor,position)
  -- A center-distance margin is deliberately stricter than entity-edge reach.
  if distance(actor.position,position)>math.min(actor.build_distance,actor.reach_distance)-1 then
    return false,"out_of_reach"
  end
  if not actor.surface.can_place_entity{name="stone-furnace",position=position,force=actor.force,
    build_check_type=defines.build_check_type.manual,forced=false} then return false,"collision" end
  -- Keep the resource grid intact and selectable, even where the game permits building over ore.
  if actor.surface.count_entities_filtered{type="resource",area={{position.x-1,position.y-1},{position.x+1,position.y+1}}}>0 then
    return false,"covers_resource"
  end
  return true
end

function M.place(actor,spec)
  assert(spec.name=="stone-furnace" and spec.direction==0 and not spec.recipe,"unsupported placement")
  local prior=storage.built[spec.address]
  if prior then
    assert(prior.valid and prior.name==spec.name and distance(prior.position,spec.position)<.001,
      "declarative entity drift; observe and replan")
    return prior,false
  end
  local ok,reason=M.site(actor,spec.position)
  assert(ok,reason)
  assert(actor.force.recipes[spec.name].enabled,"missing_research")
  local inventory=actor.get_main_inventory()
  assert(inventory.get_item_count(spec.name)>=1,"missing_item")
  assert(inventory.remove{name=spec.name,count=1}==1,"placement debit failed")
  local entity=actor.surface.create_entity{name=spec.name,position=spec.position,direction=spec.direction,
    force=actor.force,raise_built=true,move_stuck_players=false,create_build_effect_smoke=false}
  if not entity then
    assert(inventory.insert{name=spec.name,count=1}==1,"placement refund failed")
    error("placement failed after debit; refunded")
  end
  storage.built[spec.address]=entity
  storage.paid_furnaces=storage.paid_furnaces+1
  return entity,true
end

function M.transfer(actor,entity,source,destination,item,count)
  assert(entity.valid and entity.force==actor.force and actor.can_reach_entity(entity),"transfer out of reach")
  assert(count>0 and count==math.floor(count),"invalid transfer quantity")
  local stack={name=item,count=count}
  assert(source.get_item_count(item)>=count,"short_transfer")
  assert(destination.can_insert(stack),"transfer destination is full")
  local before_source,before_destination=source.get_item_count(item),destination.get_item_count(item)
  local removed=source.remove(stack)
  assert(removed==count,"transfer debit failed")
  local inserted=destination.insert(stack)
  if inserted~=count then
    assert(source.insert{name=item,count=count-inserted}==count-inserted,"transfer refund failed")
    error("partial transfer; uninserted items refunded")
  end
  assert(source.get_item_count(item)==before_source-count and destination.get_item_count(item)==before_destination+count,
    "transfer conservation failed")
  storage.transfers[#storage.transfers+1]={item=item,count=count,removed=removed,inserted=inserted,tick=game.tick}
end
return M

local power,adapter=require("power"),require("adapter")
local M={}
local function identity(e)
  return e.unit_number and tostring(e.unit_number) or e.name..":"..e.position.x..":"..e.position.y
end
local function inventory(inv)
  local out={}
  if inv then for _,s in pairs(inv.get_contents()) do assert(s.quality=="normal");out[s.name]=(out[s.name] or 0)+s.count end end
  return out
end
local function equal(a,b)
  for k,v in pairs(a) do if b[k]~=v then return false end end
  for k,v in pairs(b) do if a[k]~=v then return false end end
  return true
end
local function status(value)
  for k,v in pairs(defines.entity_status) do if v==value then return k end end
  return "unknown"
end
local function ref(e) return e and e.valid and identity(e) or nil end
local function sample()
  local a=storage.actor
  local out={tick=game.tick,entities={},deposit_remaining=0,deposits={},loose_coal=0,
    produced=a.force.get_item_production_statistics(a.surface).get_input_count("coal"),
    coal_fuel_value_j=prototypes.item.coal.fuel_value}
  for address,e in pairs(storage.coal_built or {}) do
    assert(e.valid and e.force==a.force,"coal entity disappeared or changed force")
    local r={address=address,id=identity(e),name=e.name,position=e.position,direction=e.direction,
      status=status(e.status),active=e.active}
    if e.burner then
      r.fuel=inventory(e.get_fuel_inventory());r.burning_j=e.burner.remaining_burning_fuel
      local fuel=e.burner.currently_burning
      r.burning_item=fuel and fuel.name.name or nil
      out.loose_coal=out.loose_coal+(r.fuel.coal or 0)
    end
    if e.type=="mining-drill" or e.type=="inserter" then
      r.drop_position=e.drop_position;r.drop_target=ref(e.drop_target)
    end
    if e.type=="mining-drill" then
      r.mining_target=ref(e.mining_target)
      r.energy_usage_j_per_tick=e.prototype.energy_usage
    elseif e.type=="inserter" then
      r.pickup_position=e.pickup_position;r.pickup_target=ref(e.pickup_target)
      local s=e.held_stack;r.held=s.valid_for_read and {name=s.name,count=s.count} or nil
      if r.held and r.held.name=="coal" then out.loose_coal=out.loose_coal+r.held.count end
    elseif e.type=="transport-belt" then
      r.lanes={inventory(e.get_transport_line(1)),inventory(e.get_transport_line(2))}
      for _,lane in ipairs(r.lanes) do out.loose_coal=out.loose_coal+(lane.coal or 0) end
      r.outputs={}
      for _,target in pairs(e.belt_neighbours.outputs) do r.outputs[#r.outputs+1]=identity(target) end
      table.sort(r.outputs)
    elseif e.type=="container" then
      r.contents=inventory(e.get_inventory(defines.inventory.chest))
      out.loose_coal=out.loose_coal+(r.contents.coal or 0)
    end
    out.entities[#out.entities+1]=r
  end
  table.sort(out.entities,function(a,b) return a.address<b.address end)
  if storage.coal_area then
    for _,e in pairs(a.surface.find_entities_filtered{type="resource",area=storage.coal_area}) do
      assert(e.name=="coal" and not e.prototype.infinite_resource,"mining area has incompatible resources")
      out.deposit_remaining=out.deposit_remaining+e.amount
      out.deposits[#out.deposits+1]={id=identity(e),position=e.position,amount=e.amount}
    end
    table.sort(out.deposits,function(a,b) return a.id<b.id end)
  end
  return out
end
function M.state(out)
  power.state(out)
  out.coal=sample();out.tree_events=storage.tree_events or {}
  out.coal_seed=storage.coal_seed
end
function M.begin(request,job)
  local a,args,op=storage.actor,request.args or {},request.op
  if op=="harvest_tree" then
    local t=args.target
    local e=assert(a.surface.find_entity(t.prototype,t.position),"surveyed tree disappeared")
    assert(e.type=="tree" and identity(e)==t.id and e.minable,"tree identity changed")
    assert(a.player and not a.player.cheat_mode and a.can_reach_entity(e),"tree out of reach")
    local p=e.prototype.mineable_properties
    assert(p.minable and #p.products==1,"unsupported tree products")
    local wood=p.products[1]
    assert(wood.name=="wood" and wood.type=="item" and wood.amount and
      (not wood.probability or wood.probability==1) and not wood.amount_min and not wood.amount_max,"unsupported wood yield")
    assert(a.get_main_inventory().can_insert{name="wood",count=wood.amount},"inventory full")
    job.entity=e;job.before=inventory(a.get_main_inventory());job.wood=wood.amount
    job.tree_id=t.id;job.tree_events=#(storage.tree_events or {});job.deadline=game.tick+600
  elseif op=="place_coal" then job.spec=assert(args.spec)
  elseif op=="seed_coal" then
    assert(not storage.coal_seed,"coal loop already seeded")
    for _,address in ipairs({"coal.drill","coal.refuel","coal.export"}) do
      local e=assert((storage.coal_built or {})[address],"missing burner")
      assert(e.valid and a.can_reach_entity(e) and e.get_fuel_inventory().is_empty(),"seed burner not empty or in reach")
    end
    assert(a.get_main_inventory().get_item_count("coal")>=3,"missing seed coal")
    storage.coal_area=args.mining_area
    assert(#sample().deposits==4,"expected four coal tiles under the drill")
  elseif op=="wait_coal" then
    assert(storage.coal_seed and args.ticks==3600,"measure a seeded loop for one minute")
    job.before=sample();job.inventory=inventory(a.get_main_inventory());job.position=a.position
    job.transfer_count=#storage.transfers;job.build_count=#storage.player_build_events
    job.deadline=game.tick+args.ticks+1
  else return power.begin(request,job) end
  return true
end
function M.tick(job,walk)
  local a,args,op=storage.actor,job.request.args or {},job.request.op
  if op=="harvest_tree" then
    if not job.entity.valid then
      local expected={};for k,v in pairs(job.before) do expected[k]=v end
      expected.wood=(expected.wood or 0)+job.wood
      assert(equal(expected,inventory(a.get_main_inventory())),"tree harvest inventory does not conserve products")
      assert(#storage.tree_events==job.tree_events+1 and storage.tree_events[#storage.tree_events].id==job.tree_id,"missing native tree event")
      return {id=job.tree_id,item="wood",gained=job.wood,removed=true,mining_ticks=game.tick-job.started}
    end
    assert(a.can_reach_entity(job.entity),"tree moved out of reach")
    a.update_selected_entity(job.entity.position);assert(a.selected==job.entity,"tree selection intercepted")
    a.mining_state={mining=true,position=job.entity.position}
  elseif op=="place_coal" then
    local e,added=adapter.place(a,job.spec)
    return {id=identity(e),address=job.spec.address,added=added}
  elseif op=="seed_coal" then
    local before=sample()
    for _,address in ipairs({"coal.drill","coal.refuel","coal.export"}) do
      local e=storage.coal_built[address]
      adapter.transfer(a,e,a.get_main_inventory(),e.get_fuel_inventory(),"coal",1)
    end
    storage.coal_seed={tick=game.tick,before=before,after=sample(),coal=3}
    return storage.coal_seed
  elseif op=="wait_coal" then
    assert(equal(job.inventory,inventory(a.get_main_inventory())) and equal(job.position,a.position)
      and #storage.transfers==job.transfer_count and #storage.player_build_events==job.build_count
      and a.crafting_queue_size==0 and not a.walking_state.walking and not a.mining_state.mining,
      "player intervened during the measurement")
    if game.tick-job.started>=args.ticks then
      return {before=job.before,after=sample(),idle_ticks=game.tick-job.started,
        inventory_before=job.inventory,inventory_after=inventory(a.get_main_inventory()),
        position_before=job.position,position_after=a.position,transfer_count=job.transfer_count,
        build_count=job.build_count,player_idle=true}
    end
  else return power.tick(job,walk) end
end
return M

local feed,adapter=require("feed"),require("adapter")
local M={}
local function inventory(inv)
  local out={}
  if inv then for _,s in pairs(inv.get_contents()) do
    assert(s.quality=="normal");out[s.name]=(out[s.name] or 0)+s.count
  end end
  return out
end
local function ref(e) return e and e.valid and tostring(e.unit_number) or nil end
local function equal(a,b)
  for k,v in pairs(a) do if b[k]~=v then return false end end
  for k,v in pairs(b) do if a[k]~=v then return false end end
  return true
end
remote.add_interface("iron-supply-dev",{approach=function(x,y)
  assert(not storage.job and game.tick_paused,"choose an approach at an idle boundary")
  local a=storage.actor;local best,best_distance
  local radius=math.min(7,math.min(a.build_distance,a.reach_distance)-1.5)
  local diagonal=radius*.7
  for _,offset in ipairs({{0,-radius},{diagonal,-diagonal},{-diagonal,-diagonal},
    {radius,0},{-radius,0},{0,radius},{diagonal,diagonal},{-diagonal,diagonal}}) do
    local p={x=x+offset[1],y=y+offset[2]}
    local clear=a.surface.can_place_entity{name="character",position=p,force=a.force}
    if clear then
      for _,e in pairs(a.surface.find_entities_filtered{area={{p.x-.75,p.y-.75},{p.x+.75,p.y+.75}}}) do
        if e~=a and e.type~="resource" and e.type~="item-entity" and e.type~="corpse" then clear=false;break end
      end
    end
    local distance=(p.x-a.position.x)^2+(p.y-a.position.y)^2
    if clear and (not best_distance or distance<best_distance) then best=p;best_distance=distance end
  end
  assert(best,"no clear standing point near iron placement")
  return best
end})
local function fuel(e) return {coal=e.get_fuel_inventory().get_item_count("coal"),burning_j=e.burner.remaining_burning_fuel} end
local function burner_entity(address)
  return (storage.iron_built or {})[address] or (storage.coal_built or {})[address]
    or (storage.feed_built or {})[address] or (storage.power_built or {})[address]
end
function M.observe_tick()
  feed.observe_tick()
  for address,meter in pairs(storage.iron_meters or {}) do
    local e=burner_entity(address)
    if e then
      local now=fuel(e)
      local starts=now.burning_j>meter.previous.burning_j+.001 and 1 or 0
      local delivered=now.coal-meter.previous.coal+starts
      assert(delivered>=0,"unaccounted iron-module fuel removal")
      meter.delivered=meter.delivered+delivered;meter.started=meter.started+starts;meter.previous=now
    end
  end
end
local function sample(base)
  if not base then base={};feed.state(base) end
  local a=storage.actor
  local stats=a.force.get_item_production_statistics(a.surface)
  local out={tick=game.tick,feed=base.feed,entities={},deposits={},deposit_remaining=0,
    ore_produced=stats.get_input_count("iron-ore"),ore_consumed=stats.get_output_count("iron-ore"),
    plates_produced=stats.get_input_count("iron-plate"),meters={},player_inventory=inventory(a.get_main_inventory())}
  for address,e in pairs(storage.iron_built or {}) do
    assert(e.valid and e.force==a.force,"iron entity disappeared or changed force")
    local r={address=address,id=ref(e),name=e.name,position=e.position,direction=e.direction,active=e.active,
      network_id=e.electric_network_id,energy_j=e.energy}
    if e.burner then r.fuel=inventory(e.get_fuel_inventory());r.burning_j=e.burner.remaining_burning_fuel end
    if e.type=="mining-drill" or e.type=="inserter" then
      r.drop_target=ref(e.drop_target);r.drop_position=e.drop_position
    end
    if e.type=="mining-drill" then
      local target=e.mining_target
      r.mining_target=target and target.valid and target.name or nil
    elseif e.type=="furnace" then
      r.input=inventory(e.get_inventory(defines.inventory.crafter_input));r.output=inventory(e.get_output_inventory())
      r.products=e.products_finished;r.progress=e.crafting_progress
      local recipe=e.get_recipe();r.recipe=recipe and recipe.name or nil
    elseif e.type=="inserter" then
      r.pickup_target=ref(e.pickup_target);r.pickup_position=e.pickup_position
      local s=e.held_stack;r.held=s.valid_for_read and {name=s.name,count=s.count} or nil
    elseif e.type=="container" then r.contents=inventory(e.get_inventory(defines.inventory.chest))
    elseif e.type=="transport-belt" then
      r.lanes={inventory(e.get_transport_line(1)),inventory(e.get_transport_line(2))};r.outputs={}
      for _,target in pairs(e.belt_neighbours.outputs) do r.outputs[#r.outputs+1]=ref(target) end
      table.sort(r.outputs)
    end
    out.entities[#out.entities+1]=r
  end
  table.sort(out.entities,function(a,b) return a.address<b.address end)
  for address,meter in pairs(storage.iron_meters or {}) do
    out.meters[address]={delivered=meter.delivered,started=meter.started}
  end
  for _,area in ipairs(storage.iron_areas or {}) do
    for _,e in pairs(a.surface.find_entities_filtered{type="resource",area=area}) do
      assert(e.name=="iron-ore" and not e.prototype.infinite_resource,"incompatible iron mining resource")
      out.deposit_remaining=out.deposit_remaining+e.amount
      out.deposits[#out.deposits+1]={id=e.name..":"..e.position.x..":"..e.position.y,position=e.position,amount=e.amount}
    end
  end
  table.sort(out.deposits,function(a,b) return a.id<b.id end)
  local electric=storage.power_built["power.pole"].electric_network_statistics
  out.inserter_consumed_j=electric.get_input_count("inserter")
  return out
end
function M.state(out)
  feed.state(out)
  if storage.iron_areas then out.iron=sample(out) end
end
function M.begin(request,job)
  local a,args,op=storage.actor,request.args or {},request.op
  if op=="begin_iron" then
    assert(not storage.iron_areas and not storage.iron_built,"iron module already started")
    assert(#args.mining_areas>=1 and #args.mining_areas<=2,"expected one or two mining areas")
  elseif op=="begin_iron_update" then
    assert(storage.iron_areas and storage.iron_built,"need an existing iron deployment")
    assert(#args.mining_areas>=#storage.iron_areas and #args.mining_areas<=2,"cannot remove mining areas")
    for i,area in ipairs(storage.iron_areas) do
      for j=1,2 do for k=1,2 do assert(area[j][k]==args.mining_areas[i][j][k],"existing mining area changed") end end
    end
    for address,e in pairs(storage.iron_built) do
      local expected=assert(args.expected[address],"unexpected retained entity")
      assert(e.valid and ref(e)==expected.id and e.name==expected.name and e.direction==expected.direction
        and e.position.x==expected.position.x and e.position.y==expected.position.y,"retained entity drift")
    end
    for address,_ in pairs(args.expected) do assert(storage.iron_built[address],"missing retained entity") end
  elseif op=="place_iron" then job.spec=assert(args.spec)
  elseif op=="wait_iron" then
    assert(storage.iron_areas and args.ticks==3600,"measure iron for one minute")
    job.before=sample();job.inventory=inventory(a.get_main_inventory());job.position=a.position
    job.transfers=#storage.transfers;job.builds=#storage.player_build_events
    job.deadline=game.tick+args.ticks+1
  else return feed.begin(request,job) end
  return true
end
function M.tick(job,walk)
  local a,args,op=storage.actor,job.request.args or {},job.request.op
  if op=="begin_iron" then
    storage.iron_areas=args.mining_areas;storage.iron_meters={}
    for _,group in ipairs({storage.coal_built,storage.feed_built,storage.power_built}) do
      for address,e in pairs(group) do
        if e.burner then storage.iron_meters[address]={previous=fuel(e),delivered=0,started=0} end
      end
    end
    local before=sample();assert(#before.deposits==4*#args.mining_areas,"expected four surveyed iron tiles per drill")
    return before
  elseif op=="begin_iron_update" then
    -- Extend sampling coverage without creating entities or resetting existing meters.
    storage.iron_areas=args.mining_areas
    local before=sample();assert(#before.deposits==4*#args.mining_areas,"expected four surveyed iron tiles per drill")
    return before
  elseif op=="place_iron" then
    local e,added=adapter.place(a,job.spec)
    if added and e.burner then storage.iron_meters[job.spec.address]={previous=fuel(e),delivered=0,started=0} end
    return {id=ref(e),address=job.spec.address,added=added}
  elseif op=="wait_iron" then
    assert(equal(job.inventory,inventory(a.get_main_inventory())) and equal(job.position,a.position)
      and #storage.transfers==job.transfers and #storage.player_build_events==job.builds
      and a.crafting_queue_size==0 and not a.walking_state.walking and not a.mining_state.mining,
      "player intervened during iron measurement")
    if game.tick-job.started>=args.ticks then
      return {before=job.before,after=sample(),idle_ticks=game.tick-job.started,player_idle=true,
        inventory_before=job.inventory,inventory_after=inventory(a.get_main_inventory()),
        position_before=job.position,position_after=a.position,transfer_count=job.transfers,build_count=job.builds}
    end
  else return feed.tick(job,walk) end
end
return M

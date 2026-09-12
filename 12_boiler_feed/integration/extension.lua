local coal,adapter=require("coal"),require("adapter")
local M={}
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
local function ref(e) return e and e.valid and tostring(e.unit_number) or nil end
local function boiler() return assert(storage.power_built["power.boiler"]) end
local function fuel_state()
  local e=boiler()
  return {coal=e.get_fuel_inventory().get_item_count("coal"),burning_j=e.burner.remaining_burning_fuel}
end
function M.observe_tick()
  if not storage.feed_meter then return end
  local meter,now=storage.feed_meter,fuel_state()
  local starts=now.burning_j>meter.previous.burning_j+.001 and 1 or 0
  local delivered=now.coal-meter.previous.coal+starts
  assert(delivered>=0,"unaccounted boiler fuel removal")
  meter.delivered=meter.delivered+delivered;meter.started=meter.started+starts;meter.previous=now
end
local function sample(base)
  if not base then base={};coal.state(base) end
  local out={tick=game.tick,coal=base.coal,power_entities=base.power_entities,entities={},
    delivered=storage.feed_meter and storage.feed_meter.delivered or 0,
    started_burning=storage.feed_meter and storage.feed_meter.started or 0}
  for address,e in pairs(storage.feed_built or {}) do
    assert(e.valid and e.force==storage.actor.force,"feed entity disappeared or changed force")
    local r={address=address,id=ref(e),name=e.name,position=e.position,direction=e.direction}
    if e.type=="inserter" then
      r.active=e.active;r.fuel=inventory(e.get_fuel_inventory());r.burning_j=e.burner.remaining_burning_fuel
      r.pickup_target=ref(e.pickup_target);r.drop_target=ref(e.drop_target)
      local s=e.held_stack;r.held=s.valid_for_read and {name=s.name,count=s.count} or nil
    else
      r.lanes={inventory(e.get_transport_line(1)),inventory(e.get_transport_line(2))};r.outputs={}
      for _,target in pairs(e.belt_neighbours.outputs) do r.outputs[#r.outputs+1]=ref(target) end
      table.sort(r.outputs)
    end
    out.entities[#out.entities+1]=r
  end
  table.sort(out.entities,function(a,b) return a.address<b.address end)
  local force=storage.actor.force
  out.research_progress=force.technologies.logistics.researched and 1 or
    (force.current_research and force.current_research.name=="logistics" and force.research_progress or 0)
  out.researched=force.technologies.logistics.researched
  -- Conservative thermal reserve: all steam enthalpy, plus stored electricity.
  out.power_reserve_j=0
  for _,address in ipairs({"power.boiler","power.engine","power.lab"}) do
    local e=storage.power_built[address]
    if e then
      out.power_reserve_j=out.power_reserve_j+e.energy
      if e.burner then out.power_reserve_j=out.power_reserve_j+e.burner.remaining_burning_fuel+
        e.get_fuel_inventory().get_item_count("coal")*prototypes.item.coal.fuel_value end
      for i=1,e.fluids_count do
        local f=e.get_fluid(i)
        if f and f.name=="steam" then
          local p=prototypes.fluid.steam
          out.power_reserve_j=out.power_reserve_j+f.amount*math.max(0,f.temperature-p.default_temperature)*p.heat_capacity
        end
      end
    end
  end
  return out
end
function M.state(out)
  coal.state(out)
  if storage.feed_meter then out.feed=sample(out) end
end
function M.begin(request,job)
  local a,args,op=storage.actor,request.args or {},request.op
  if op=="begin_feed" then
    assert(not storage.feed_meter and not storage.feed_built,"feed already started")
  elseif op=="place_feed" then job.spec=assert(args.spec)
  elseif op=="start_feed_research" then
    local tech=a.force.technologies.logistics
    local lab=storage.power_built["power.lab"]
    assert(not tech.researched and not a.force.current_research,"research already active or complete")
    assert(tech.research_unit_count==args.packs and tech.research_unit_energy==900,"logistics runtime contract changed")
    assert(a.can_reach_entity(lab) and lab.get_inventory(defines.inventory.lab_input).is_empty(),"lab not empty or in reach")
    assert(a.get_main_inventory().get_item_count("automation-science-pack")>=args.packs,"missing research packs")
  elseif op=="wait_feed" then
    assert(storage.feed_meter and args.ticks==3600,"measure one minute")
    job.before=sample();job.inventory=inventory(a.get_main_inventory());job.position=a.position
    job.transfers=#storage.transfers;job.builds=#storage.player_build_events
    job.deadline=game.tick+args.ticks+1
  else return coal.begin(request,job) end
  return true
end
function M.tick(job,walk)
  local a,args,op=storage.actor,job.request.args or {},job.request.op
  if op=="begin_feed" then
    local baseline=sample()
    storage.feed_meter={previous=fuel_state(),delivered=0,started=0}
    return baseline
  elseif op=="place_feed" then
    local e,added=adapter.place(a,job.spec)
    return {id=ref(e),address=job.spec.address,added=added}
  elseif op=="start_feed_research" then
    local lab=storage.power_built["power.lab"]
    adapter.transfer(a,lab,a.get_main_inventory(),lab.get_inventory(defines.inventory.lab_input),"automation-science-pack",args.packs)
    assert(a.force.add_research("logistics"),"research refused")
    return {technology="logistics",packs=args.packs,tick=game.tick}
  elseif op=="wait_feed" then
    assert(equal(job.inventory,inventory(a.get_main_inventory())) and equal(job.position,a.position)
      and #storage.transfers==job.transfers and #storage.player_build_events==job.builds
      and a.crafting_queue_size==0 and not a.walking_state.walking and not a.mining_state.mining,
      "player intervened during feed measurement")
    if game.tick-job.started>=args.ticks then
      return {before=job.before,after=sample(),idle_ticks=game.tick-job.started,player_idle=true,
        inventory_before=job.inventory,inventory_after=inventory(a.get_main_inventory()),
        position_before=job.position,position_after=a.position,transfer_count=job.transfers,build_count=job.builds}
    end
  else return coal.tick(job,walk) end
end
return M

local adapter=require("adapter")
local M={}
local function inventory(inv)
  local out={}
  if inv then for _,s in pairs(inv.get_contents()) do out[s.name]=(out[s.name] or 0)+s.count end end
  return out
end
local function status(value)
  for k,v in pairs(defines.entity_status) do if v==value then return k end end
  return "unknown"
end
local function station(name)
  return assert((storage.power_built or {})["power."..name],"missing power station: "..name)
end
function M.state(out)
  out.power_entities={}
  for address,e in pairs(storage.power_built or {}) do
    assert(e.valid,"power entity disappeared")
    local r={address=address,id=tostring(e.unit_number),name=e.name,position=e.position,direction=e.direction,
      status=status(e.status),energy_j=e.energy,network_id=e.electric_network_id,fluids=e.get_fluid_contents()}
    if e.type=="boiler" then r.fuel=inventory(e.get_fuel_inventory());r.burning_j=e.burner.remaining_burning_fuel end
    if e.type=="lab" then r.science=inventory(e.get_inventory(defines.inventory.lab_input)) end
    if e.type=="electric-pole" then
      local stats=e.electric_network_statistics
      -- Electricity inputs are consumers; outputs are generators. Electric
      -- histories are per tick, unlike item histories (per minute).
      r.generated_j=stats.get_output_count("steam-engine")
      r.lab_consumed_j=stats.get_input_count("lab")
      r.generation_kw_5s=stats.get_flow_count{name="steam-engine",category="output",
        precision_index=defines.flow_precision_index.five_seconds}*60/1000
      r.lab_load_kw_5s=stats.get_flow_count{name="lab",category="input",
        precision_index=defines.flow_precision_index.five_seconds}*60/1000
    end
    out.power_entities[#out.power_entities+1]=r
  end
  table.sort(out.power_entities,function(a,b) return a.address<b.address end)
  out.cursor_placements=storage.cursor_placements or {}
  out.player_build_events=storage.player_build_events or {}
  local force=storage.actor.force
  out.automation_progress=force.technologies.automation.researched and 1 or
    (force.current_research and force.current_research.name=="automation" and force.research_progress or 0)
  out.science_produced=force.get_item_production_statistics(storage.actor.surface).get_input_count("automation-science-pack")
end
function M.begin(request,job)
  local args,a=request.args or {},storage.actor
  if request.op=="walk_to" then
    local p=assert(args.position)
    assert((a.position.x-p.x)^2+(a.position.y-p.y)^2<=64^2,"walk target beyond bounded range")
    local box=a.prototype.collision_box
    local mask={layers={},consider_tile_transitions=false}
    for k,v in pairs(a.prototype.collision_mask.layers) do mask.layers[k]=v end
    mask.layers.water_tile=true;job.start=a.position
    job.request_id=a.surface.request_path{bounding_box={{box.left_top.x-.25,box.left_top.y-.25},{box.right_bottom.x+.25,box.right_bottom.y+.25}},
      collision_mask=mask,start=a.position,goal=p,force=a.force,radius=.1,entity_to_ignore=a,can_open_gates=false,
      max_gap_size=0,path_resolution_modifier=1,pathfind_flags={allow_destroy_friendly_entities=false,
      allow_paths_through_own_entities=false,cache=false,prefer_straight_paths=true}}
  elseif request.op=="place_power" then job.spec=assert(args.spec)
  elseif request.op=="preflight_power" then
    for _,spec in ipairs(args.specs) do
      assert(a.surface.can_place_entity{name=spec.name,position=spec.position,direction=spec.direction,force=a.force,
        build_check_type=defines.build_check_type.manual},"power site blocked: "..spec.address)
    end
  elseif request.op=="fuel_power" then
    job.entity=station("boiler");assert(args.coal==3,"this finite method budgets three coal")
    assert(a.can_reach_entity(job.entity) and a.get_main_inventory().get_item_count("coal")>=args.coal,"fuel not available within reach")
  elseif request.op=="research_lab" then
    assert(args.technology=="automation" and args.packs==10,"unsupported finite research contract")
    job.entity=station("lab")
    local tech=a.force.technologies.automation
    assert(not tech.researched and not a.force.current_research,"research already active or complete")
    assert(a.can_reach_entity(job.entity) and a.get_main_inventory().get_item_count("automation-science-pack")>=10,"science not available within reach")
    assert(job.entity.get_inventory(defines.inventory.lab_input).is_empty(),"lab has prior science")
    assert(tech.research_unit_count==10 and tech.research_unit_energy==600,"research contract changed")
    job.deadline=game.tick+6600
  else return false end
  return true
end
function M.tick(job,walk)
  local args,op=job.request.args or {},job.request.op
  if op=="walk_to" and job.path and walk(job) then return {position=storage.actor.position,path=job.path}
  elseif op=="place_power" then
    local e,added=adapter.place(storage.actor,job.spec)
    return {id=tostring(e.unit_number),address=job.spec.address,added=added}
  elseif op=="preflight_power" then return {clear=true,specs=args.specs}
  elseif op=="fuel_power" then
    adapter.transfer(storage.actor,job.entity,storage.actor.get_main_inventory(),job.entity.get_fuel_inventory(),"coal",args.coal)
    return {loaded_coal=args.coal,station_id=tostring(job.entity.unit_number)}
  elseif op=="research_lab" then
    if not job.loaded then
      adapter.transfer(storage.actor,job.entity,storage.actor.get_main_inventory(),job.entity.get_inventory(defines.inventory.lab_input),"automation-science-pack",10)
      assert(storage.actor.force.add_research("automation"),"research request refused")
      job.loaded=game.tick
    elseif storage.actor.force.technologies.automation.researched then
      assert(job.entity.get_inventory(defines.inventory.lab_input).get_item_count("automation-science-pack")==0,"science not consumed")
      return {technology="automation",observed=true,science_consumed=10,research_ticks=game.tick-job.loaded}
    end
  end
end
return M

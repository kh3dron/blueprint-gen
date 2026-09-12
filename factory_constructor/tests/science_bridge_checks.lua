-- Run with Lua/LuaJIT and the repository root as the first script argument.
-- Native objects below are stand-ins; this suite never connects to Factorio.
local root=assert(arg[1],"repository root argument is required")..'/'
local function check_error(fn,needle)
  local ok,err=pcall(fn);assert(not ok and tostring(err):find(needle,1,true),tostring(err))
end
local function inv(contents)
  return {get_contents=function()
    local r={};for name,count in pairs(contents) do if count>0 then r[#r+1]={name=name,count=count,quality='normal'} end end;return r
  end,get_item_count=function(name)return contents[name] or 0 end,is_empty=function()return next(contents)==nil end}
end
-- Exercise the real paid cursor adapter with a native-player stand-in.
defines={inventory={crafter_input=1,chest=2},build_mode={normal=0},entity_status={working=1}}
prototypes={entity={['assembling-machine-1']={crafting_categories={crafting=true}},['copper-ore']={type='resource'},coal={type='resource'}},item={coal={fuel_value=4000000}},fluid={steam={default_temperature=15,heat_capacity=200}}}
game={tick=10}
storage={built={},power_built={},paid_furnaces=0,science_areas={}}
local recipes={['assembling-machine-1']={enabled=true},['iron-chest']={enabled=true},['iron-gear-wheel']={name='iron-gear-wheel',enabled=true,categories={'crafting'},ingredients={{type='item',name='iron-plate',amount=2}}}}
local slot={name='assembling-machine-1',count=2,quality={name='normal'},valid_for_read=true}
local cursor={valid_for_read=false}
local function swap(a,b)
  for _,k in ipairs({'name','count','quality','valid_for_read'}) do local v=a[k];a[k]=b[k];b[k]=v end
  return true
end
cursor.swap_stack=function(other)return swap(cursor,other)end
local player={connected=true,cheat_mode=false,cursor_stack=cursor,index=1}
local actor={position={x=0,y=0},build_distance=10,reach_distance=10,force={recipes=recipes},player=player}
player.character=actor
local main={get_contents=function()return slot.valid_for_read and {{name=slot.name,count=slot.count,quality='normal'}} or {} end,find_item_stack=function(name)return slot.valid_for_read and slot.name==name and slot or nil end}
actor.get_main_inventory=function()return main end
local built_entity
player.can_build_from_cursor=function()return true end
player.build_from_cursor=function(p)
  local name=cursor.name
  assert(cursor.count>0);cursor.count=cursor.count-1
  if cursor.count==0 then cursor.valid_for_read=false end
  built_entity={valid=true,name=name,type=name=='iron-chest' and 'container' or 'assembling-machine',unit_number=100+#(storage.cursor_placements or {}),position=p.position,direction=p.direction,force=actor.force}
  built_entity.get_inventory=function()return inv({})end;built_entity.get_output_inventory=built_entity.get_inventory
  local selected
  built_entity.get_recipe=function()return selected end
  built_entity.set_recipe=function(name)selected=recipes[name];return {} end
end
actor.surface={find_entity=function()return built_entity end}
package.loaded.transfers={site=function()return true end,transfer=function()end}
package.loaded.cursor=dofile(root..'10_powered_lab/integration/adapter.lua')
package.loaded.iron_adapter={site=function()return true end,transfer=function()end,place=function()error('unexpected delegate')end}
local adapter=dofile(root..'factory_constructor/integration/science_adapter.lua')
local spec={address='science.gear',name='assembling-machine-1',position={x=2,y=2},direction=0,recipe='iron-gear-wheel'}
local e,added=adapter.place(actor,spec)
assert(added and slot.count==1 and not cursor.valid_for_read and e.get_recipe().name=='iron-gear-wheel')
assert(#storage.cursor_placements==1 and #storage.science_recipe_events==1)
local same,again=adapter.place(actor,spec);assert(same==e and not again and slot.count==1)
check_error(function()adapter.place(actor,{address=spec.address,name=spec.name,position=spec.position,direction=0})end,'recipe drift')
assert(slot.count==1 and #storage.cursor_placements==1)
print('Paid native cursor placement, recipe setup, retry, and recipe drift tests passed')

-- Iron collection chests use the same item debit and native placement receipt.
slot.name='iron-chest';slot.count=2
local chest_spec={address='science.output.chest',name='iron-chest',position={x=3,y=2},direction=0}
local chest,chest_added=adapter.place(actor,chest_spec)
assert(chest_added and chest.name=='iron-chest' and slot.count==1)
assert(storage.cursor_placements[2].name=='iron-chest' and #storage.science_recipe_events==1)
local chest_again,chest_rebuilt=adapter.place(actor,chest_spec)
assert(chest_again==chest and not chest_rebuilt and slot.count==1 and #storage.cursor_placements==2)
check_error(function()adapter.place(actor,{address=chest_spec.address,name='iron-chest',position=chest_spec.position,direction=0,recipe='iron-gear-wheel'})end,'recipe requires an assembler')
assert(slot.count==1)
print('Paid iron chest placement, retry, and inappropriate recipe refusal tests passed')

-- Exercise observation using read-only stand-ins for resources and devices.
local fuel_contents={coal=1}
local furnace={valid=true,unit_number=7,name='stone-furnace',type='furnace',position={x=0,y=0},direction=0,force=actor.force,burner={remaining_burning_fuel=1000,currently_burning={name={name='coal'}}},energy=1600,prototype={energy_usage=1500},fluids_count=0}
furnace.get_recipe=function()return {name='iron-plate'}end
furnace.get_fuel_inventory=function()return inv(fuel_contents)end
local electrical={input_counts={['assembling-machine-1']=300000,inserter=50000},output_counts={['steam-engine']=351000}}
local function pole(id)return {valid=true,unit_number=id,name='small-electric-pole',type='electric-pole',position={x=id,y=0},direction=0,force=actor.force,energy=0,fluids_count=0,electric_network_id=1,electric_network_statistics=electrical} end
local deposits={}
for i,name in ipairs({'coal','copper-ore'}) do deposits[i]={name=name,position={x=i,y=0},amount=100,prototype={infinite_resource=false}} end
actor.surface={find_entities_filtered=function(q)return {deposits[q.area[1][1]]} end}
actor.force.get_item_production_statistics=function()return {get_input_count=function()return 42 end,get_output_count=function()return 12 end}end
actor.get_main_inventory=function()return inv({coal=2})end
actor.crafting_queue_size=0;actor.walking_state={walking=false};actor.mining_state={mining=false}
storage={actor=actor,iron_built={['iron.furnace']=furnace,['iron.pole']=pole(8)},power_built={['power.pole']=pole(9)},iron_areas={},transfers={},player_build_events={}}
local delegated_ticks=0
package.loaded.iron={state=function(out)out.iron={entities={}}end,observe_tick=function()delegated_ticks=delegated_ticks+1 end,begin=function()return false end,tick=function()end}
package.loaded.adapter=adapter
package.loaded.science_walking=dofile(root..'factory_constructor/integration/science_walking.lua')
local science=dofile(root..'factory_constructor/integration/science.lua')
local begin={op='begin_science',args={mining_areas={{resource='coal',area={{1,0},{2,1}}},{resource='copper-ore',area={{2,0},{3,1}}}}}}
local job={request=begin,started=game.tick};assert(science.begin(begin,job))
local baseline=science.tick(job)
assert(baseline.deposit_remaining==200 and baseline.deposit_remaining_by_resource.coal==100)
assert(baseline.electric_consumed_j==350000 and baseline.electric_generated_j==351000)
assert(#baseline.electric_networks['1'].poles==2)
assert(baseline.production['automation-science-pack'].produced==42)
fuel_contents.coal=0;furnace.burner.remaining_burning_fuel=3999500;game.tick=11;science.observe_tick()
local state={};science.state(state)
assert(delegated_ticks==1 and state.science.meters['iron.furnace'].started==1)
assert(state.science.meters['iron.furnace'].delivered==0 and state.science.meters['iron.furnace'].burned_j==1500)
fuel_contents.coal=1;game.tick=12;science.observe_tick();science.state(state)
assert(state.science.meters['iron.furnace'].delivered==1)
local wait={op='wait_science',args={ticks=3600}};local measure={request=wait,started=game.tick};assert(science.begin(wait,measure))
actor.walking_state.walking=true
check_error(function()science.tick(measure)end,'player intervened')
actor.walking_state.walking=false;game.tick=measure.started+3600
local result=science.tick(measure);assert(result.player_idle and result.idle_ticks==3600)
furnace.direction=4;check_error(function()science.state({})end,'configuration drift')
print('Typed deposits, unique electric networks, fuel conservation, idle, and retention tests passed')

-- Burner inserters receive native initial wood when the player places them.
-- Its exhaustion must not invent a coal start, delivery, or inventory item.
furnace.direction=0;furnace.burner.currently_burning={name={name='wood'}}
furnace.burner.remaining_burning_fuel=1000;fuel_contents.coal=1
storage.science_areas=nil;storage.science_built=nil;storage.science_measurement_started=nil
local restart={request=begin,started=game.tick};assert(science.begin(begin,restart));science.tick(restart)
furnace.burner.remaining_burning_fuel=500;game.tick=game.tick+1;science.observe_tick();science.state(state)
local meter=state.science.meters['iron.furnace']
assert(meter.initial_burning_item=='wood' and meter.initial_burning_j==1000)
assert(meter.started==0 and meter.delivered==0 and meter.burned_j==500)
furnace.burner.currently_burning={name={name='coal'}};furnace.burner.remaining_burning_fuel=3999500
fuel_contents.coal=0;game.tick=game.tick+1;science.observe_tick();science.state(state)
meter=state.science.meters['iron.furnace']
assert(meter.started==1 and meter.delivered==0 and meter.burned_j==1500)
furnace.burner.currently_burning={name={name='wood'}};furnace.burner.remaining_burning_fuel=400
check_error(science.observe_tick,'non-native wood appeared')
print('Native initial wood exhaustion and later fuel-mutation refusal tests passed')

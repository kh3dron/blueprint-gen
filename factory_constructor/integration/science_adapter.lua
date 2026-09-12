-- Declarative science placement uses the same paid LuaPlayer cursor path as iron.
local iron,cursor=require("iron_adapter"),require("cursor")
local M={site=iron.site,transfer=iron.transfer}
local allowed={['burner-mining-drill']=true,['stone-furnace']=true,inserter=true,
  ['burner-inserter']=true,['transport-belt']=true,['wooden-chest']=true,['iron-chest']=true,
  ['small-electric-pole']=true,['assembling-machine-1']=true}

function M.place(actor,spec)
  assert(type(spec)=="table" and type(spec.address)=="string","placement needs a stable address")
  if string.sub(spec.address,1,8)~="science." then return iron.place(actor,spec) end
  assert(allowed[spec.name],"unsupported science entity")
  assert(storage.science_areas,"begin_science must precede science placement")
  local recipe
  if spec.recipe then
    assert(spec.name=="assembling-machine-1" and type(spec.recipe)=="string","recipe requires an assembler")
    recipe=assert(actor.force.recipes[spec.recipe],"unknown recipe")
    assert(recipe.enabled,"missing_research")
    local categories=prototypes.entity[spec.name].crafting_categories
    local compatible=false
    for _,category in pairs(recipe.categories) do if categories[category] then compatible=true end end
    assert(compatible,"recipe is incompatible with assembler")
    for _,ingredient in pairs(recipe.ingredients) do
      assert(ingredient.type=="item","science placement supports item-only recipes")
    end
  end
  storage.science_built=storage.science_built or {}
  local prior=storage.science_built[spec.address]
  if prior and prior.valid and prior.type=="assembling-machine" then
    local current=prior.get_recipe()
    assert((current and current.name or nil)==spec.recipe,"declarative recipe drift")
  end
  -- The shared cursor adapter does not select recipes. Keep its item accounting
  -- and native build-event checks intact, then configure the empty paid machine.
  local placement={address=spec.address,name=spec.name,position=spec.position,direction=spec.direction}
  local entity,added=cursor.place(actor,placement,{allowed=allowed,built=storage.science_built})
  if added and recipe then
    assert(entity.get_inventory(defines.inventory.crafter_input).is_empty()
      and entity.get_output_inventory().is_empty(),"new assembler is not empty")
    local removed=entity.set_recipe(recipe.name)
    assert(next(removed)==nil,"recipe selection removed items")
    local actual=entity.get_recipe()
    assert(actual and actual.name==recipe.name,"recipe selection failed")
    storage.science_recipe_events=storage.science_recipe_events or {}
    storage.science_recipe_events[#storage.science_recipe_events+1]={tick=game.tick,address=spec.address,
      id=tostring(entity.unit_number),recipe=recipe.name,player_index=actor.player.index}
  end
  return entity,added
end
return M

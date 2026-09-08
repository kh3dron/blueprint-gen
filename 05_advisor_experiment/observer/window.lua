-- Pure counter-delta bookkeeping; called every tick while a window is active.
local M = {}

function M.start(tick, entities, signature, generation)
  local counters = {}
  for _, e in ipairs(entities) do counters[e.id] = e.products_finished end
  return {start_tick = tick, last_tick = tick, counters = counters, produced = {},
          signature = signature, generation = generation, invalid = {}}
end

function M.advance(window, tick, entities, signature, generation, products)
  if tick ~= window.last_tick + 1 then window.invalid["observation ticks were skipped"] = true end
  if signature ~= window.signature then window.invalid["machine configuration changed"] = true end
  if generation ~= window.generation then window.invalid["world configuration changed"] = true end
  for _, e in ipairs(entities) do
    local old, current = window.counters[e.id], e.products_finished
    if old and current then
      local delta = current - old
      if delta < 0 then window.invalid["production counter reset"] = true end
      if delta > 0 then
        if not e.recipe or not products[e.recipe] or e.quality ~= "normal" or e.recipe_quality ~= "normal"
          or e.speed_bonus ~= 0 or e.productivity_bonus ~= 0 or #e.modules > 0 then
          window.invalid["unsupported recipe or machine modifiers"] = true
        else
          for item, amount in pairs(products[e.recipe]) do
            window.produced[item] = (window.produced[item] or 0) + delta * amount
          end
        end
      end
    elseif current and current > 0 then
      window.invalid["new production counter appeared"] = true
    end
    window.counters[e.id] = current
  end
  window.last_tick = tick
end

function M.finish(window)
  local errors = {}
  for error in pairs(window.invalid) do errors[#errors + 1] = error end
  table.sort(errors)
  return {start_tick = window.start_tick, end_tick = window.last_tick,
          generation = window.generation, source = "automated", produced = window.produced,
          valid = #errors == 0, invalid_reasons = errors,
          method = "per-tick machine products_finished deltas times deterministic recipe outputs"}
end

return M

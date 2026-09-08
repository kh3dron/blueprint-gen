package.path = arg[1] .. "/?.lua;" .. package.path
local window = require("window")
local products = {cable = {cable = 2}}
local function entity(counter)
  return {id = "1", recipe = "cable", products_finished = counter, quality = "normal",
          recipe_quality = "normal", speed_bonus = 0, productivity_bonus = 0, modules = {}}
end
local function run_case(edit, expected_error)
  local state = window.start(100, {entity(40)}, "stable", 1)
  local e, tick, signature, generation = entity(41), 101, "stable", 1
  e, tick, signature, generation = edit(e, tick, signature, generation)
  window.advance(state, tick, {e}, signature, generation, products)
  local result = window.finish(state)
  if expected_error then
    assert(not result.valid, "invalid interval was accepted")
    assert(table.concat(result.invalid_reasons, "; "):find(expected_error, 1, true))
  else
    assert(result.valid)
    assert(result.produced.cable == 2, "lifetime count must not become window output")
  end
end
run_case(function(e,t,s,g) return e,t,s,g end)
run_case(function(e,t,s,g) return e,t+1,s,g end, "ticks were skipped")
run_case(function(e,t,s,g) return e,t,"edited",g end, "machine configuration changed")
run_case(function(e,t,s,g) return e,t,s,g+1 end, "world configuration changed")
run_case(function(e,t,s,g) e.products_finished=0; return e,t,s,g end, "production counter reset")
run_case(function(e,t,s,g) e.id="2"; return e,t,s,g end, "new production counter appeared")
run_case(function(e,t,s,g) e.productivity_bonus=0.1; return e,t,s,g end, "unsupported recipe or machine modifiers")
local state = window.start(100, {entity(40)}, "stable", 1)
window.advance(state, 101, {entity(41)}, "edited", 1, products)
window.advance(state, 102, {entity(42)}, "stable", 1, products)
assert(not window.finish(state).valid, "restoring the old recipe must not restore the interval")
print("8 window cases passed")

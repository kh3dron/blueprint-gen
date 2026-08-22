-- Loads Factorio recipe prototype files with a stub `data:extend` and prints JSON to stdout.
-- Usage: luajit extract.lua data/base/prototypes/recipe.lua [...more files] > data/recipes.json
local recipes = {}
data = { extend = function(_, protos)
  for _, p in ipairs(protos) do
    if p.type == "recipe" then recipes[#recipes + 1] = p end
  end
end }

local function is_array(t)
  local n = 0
  for _ in pairs(t) do n = n + 1 end
  return n == #t
end

local function json(v, out)
  local ty = type(v)
  if ty == "table" then
    if is_array(v) then
      out[#out + 1] = "["
      for i, x in ipairs(v) do
        if i > 1 then out[#out + 1] = "," end
        json(x, out)
      end
      out[#out + 1] = "]"
    else
      out[#out + 1] = "{"
      local first = true
      for k, x in pairs(v) do
        if not first then out[#out + 1] = "," end
        first = false
        out[#out + 1] = string.format("%q:", tostring(k))
        json(x, out)
      end
      out[#out + 1] = "}"
    end
  elseif ty == "string" then
    out[#out + 1] = string.format("%q", v):gsub("\\\n", "\\n")
  elseif ty == "number" or ty == "boolean" then
    out[#out + 1] = tostring(v)
  else
    out[#out + 1] = "null"
  end
end

for _, path in ipairs(arg) do
  local f = assert(io.open(path)); local src = f:read("*a"); f:close()
  src = src:gsub("data:extend%s*\n%s*%(", "data:extend(")
  local chunk = assert(loadstring(src, "@" .. path))
  chunk()
  for i = #recipes, 1, -1 do
    if not recipes[i].__src then recipes[i].__src = path else break end
  end
end

local out = {}
json(recipes, out)
io.write(table.concat(out), "\n")

-- Loads Factorio entity prototype files in a permissive environment (every unknown global,
-- require() result, and util helper resolves to a proxy that tolerates any index/call/arith)
-- and prints one JSON object per prototype: type, name, collision_box, icon.
-- Usage: luajit extract_entities.lua <entity .lua files...> > entities.json
local protos = {}
local proxy
local mt = {}
mt.__index = function() return proxy end
mt.__newindex = function() end
mt.__call = function() return proxy end
mt.__add = function() return 0 end
mt.__sub, mt.__mul, mt.__div, mt.__unm, mt.__mod, mt.__pow = mt.__add, mt.__add, mt.__add, mt.__add, mt.__add, mt.__add
mt.__concat = function() return "" end
mt.__len = function() return 0 end
mt.__lt = function() return false end
mt.__le = mt.__lt
proxy = setmetatable({}, mt)

setmetatable(_G, { __index = function() return proxy end })
require = function() return proxy end
data = {
  extend = function(_, list)
    for _, p in ipairs(list) do
      if type(p) == "table" and type(p.name) == "string" and type(p.type) == "string" then
        protos[#protos + 1] = p
      end
    end
  end,
  raw = proxy,
}
table.deepcopy = function(t) return t end
util = setmetatable({
  by_pixel = function(x, y) return { x / 32, y / 32 } end,
  by_pixel_hr = function(x, y) return { x / 64, y / 64 } end,
  table = { deepcopy = function(t) return t end },
}, mt)

local function num(v) return type(v) == "number" and v or nil end

for _, path in ipairs(arg) do
  local f = assert(io.open(path)); local src = f:read("*a"); f:close()
  -- Lua 5.1 rejects `f\n(args)`; join the call onto one line.
  src = src:gsub("([%w_])%s*\n%s*%(", "%1(")
  local chunk, err = loadstring(src, "@" .. path)
  if not chunk then
    io.stderr:write("PARSE " .. err .. "\n")
  else
    local ok, e = pcall(chunk)
    if not ok then io.stderr:write("RUN " .. tostring(e) .. "\n") end
  end
end

io.write("[\n")
local n = 0
for _, p in ipairs(protos) do
  local cb = p.collision_box
  local box = "null"
  if type(cb) == "table" and type(cb[1]) == "table" and num(cb[1][1]) and num(cb[1][2])
     and type(cb[2]) == "table" and num(cb[2][1]) and num(cb[2][2]) then
    box = string.format("[%g,%g,%g,%g]", cb[1][1], cb[1][2], cb[2][1], cb[2][2])
  end
  local icon = "null"
  if type(p.icon) == "string" then
    icon = string.format("%q", p.icon)
  elseif type(p.icons) == "table" and type(p.icons[1]) == "table" and type(p.icons[1].icon) == "string" then
    icon = string.format("%q", p.icons[1].icon)
  end
  if n > 0 then io.write(",\n") end
  io.write(string.format('{"type":%q,"name":%q,"collision_box":%s,"icon":%s}', p.type, p.name, box, icon))
  n = n + 1
end
io.write("\n]\n")
io.stderr:write(n .. " prototypes\n")

local cursor=require("cursor")
local M={site=cursor.site,transfer=cursor.transfer}
local allowed={['burner-mining-drill']=true,['burner-inserter']=true,['transport-belt']=true,['wooden-chest']=true}
function M.place(actor,spec)
  if allowed[spec.name] then
    storage.coal_built=storage.coal_built or {}
    return cursor.place(actor,spec,{allowed=allowed,built=storage.coal_built})
  end
  assert(not (storage.coal_built or {})[spec.address],"declarative entity drift")
  return cursor.place(actor,spec)
end
return M

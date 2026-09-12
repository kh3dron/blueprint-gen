local coal,cursor=require("coal_adapter"),require("cursor")
local M={site=coal.site,transfer=coal.transfer}
function M.place(actor,spec)
  if string.sub(spec.address,1,5)=="feed." then
    assert(spec.name=="burner-inserter" or spec.name=="transport-belt","unsupported feed placement")
    storage.feed_built=storage.feed_built or {}
    return cursor.place(actor,spec,{allowed={['burner-inserter']=true,['transport-belt']=true},built=storage.feed_built})
  end
  return coal.place(actor,spec)
end
return M

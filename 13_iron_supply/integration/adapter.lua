local feed,cursor=require("feed_adapter"),require("cursor")
local M={site=feed.site,transfer=feed.transfer}
local allowed={['burner-mining-drill']=true,['stone-furnace']=true,inserter=true,
  ['burner-inserter']=true,['transport-belt']=true,['wooden-chest']=true,['small-electric-pole']=true}
function M.place(actor,spec)
  if string.sub(spec.address,1,5)=="iron." then
    storage.iron_built=storage.iron_built or {}
    return cursor.place(actor,spec,{allowed=allowed,built=storage.iron_built})
  end
  return feed.place(actor,spec)
end
return M

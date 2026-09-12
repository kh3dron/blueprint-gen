package.preload.feed=function() return {} end
package.preload.adapter=function() return {} end
local interface
remote={add_interface=function(_,value) interface=value end}
local blocked=true
local surface={
  can_place_entity=function() return true end,
  find_entities_filtered=function(args)
    local x=(args.area[1][1]+args.area[2][1])/2
    local y=(args.area[1][2]+args.area[2][2])/2
    if blocked and x==3 and y==0 then return {{type="container"}} end
    return {{type="resource"}}
  end
}
storage={actor={surface=surface,position={x=0,y=0},build_distance=10,reach_distance=10}}
game={tick_paused=true}
dofile(arg[1])
local point,extra=interface.approach(10,0)
assert(point and extra==nil,"approach must return exactly one JSON value")
assert(point.x~=3 or point.y~=0,"occupied nearest point was selected")
assert((point.x-10)^2+point.y^2<9^2,"point is outside native construction reach")
blocked=false
point=interface.approach(10,0)
assert(point.x==3 and point.y==0,"nearest clear approach was not selected")
surface.can_place_entity=function() return false end
local ok,err=pcall(interface.approach,10,0)
assert(not ok and tostring(err):find("no clear standing point",1,true))

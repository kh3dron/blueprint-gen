-- Exercise the actual reconnect handler with a logged-off (invalid) reference.
package.preload.live=function() return true end
local handlers={}
defines={events={on_player_created=1,on_player_joined_game=2,on_player_crafted_item=3,on_tick=4}}
script={on_event=function(id,fn) handlers[id]=fn end,get_event_handler=function() return function() end end}
remote={add_interface=function() end}
local written
helpers={table_to_json=function(value) return value end,write_file=function(path,value) written=value end}
dofile(arg[1])
local player={index=1,cheat_mode=false}
local inventory={{name="iron-plate",quality="normal",count=7}}
local actor={valid=true,unit_number=12,position={x=1,y=2},player=player,
  get_main_inventory=function() return {get_contents=function() return inventory end} end}
player.character=actor
game={tick=123,tick_paused=true,get_player=function() return player end}
local function reset()
  storage={actor={valid=false},capture_player=1,attachment={after={character_id="12"}}}
  written=nil
end
reset()
handlers[2]{player_index=1}
assert(storage.actor==actor and player.character==actor)
assert(written.character_id=="12" and written.player_index==1 and written.inventory["iron-plate"]==7)
local function refuses(change,undo,expected)
  reset();change()
  local old=storage.actor
  local ok,err=pcall(handlers[2],{player_index=1})
  assert(not ok and tostring(err):find(expected,1,true),tostring(err))
  assert(storage.actor==old and written==nil)
  undo()
end
refuses(function() actor.unit_number=13 end,function() actor.unit_number=12 end,"identity changed")
refuses(function() player.character=nil end,function() player.character=actor end,"identity changed")
refuses(function() player.index=2 end,function() player.index=1 end,"unexpected experiment player")
refuses(function() player.cheat_mode=true end,function() player.cheat_mode=false end,"attribution changed")
refuses(function() storage.job={} end,function() end,"idle boundary")
refuses(function() game.tick_paused=false end,function() game.tick_paused=true end,"idle boundary")

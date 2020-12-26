from colors import GREEN
from commands.say import SayCommand
from commands.client import ClientCommand
from cvars import ConVar
from contextlib import contextmanager
from entities.entity import BaseEntity
from events import Event
from filters.players import PlayerIter
from listeners import ListenerManager
from listeners import ListenerManagerDecorator
from listeners import OnClientActive, OnPlayerRunCommand, OnLevelInit
from listeners.tick import Repeat, Delay

from messages import HudMsg
from messages.base import SayText2

from paths import PLUGIN_DATA_PATH, GAME_PATH
from players.constants import PlayerButtons, HitGroup, PlayerStates
from players.entity import Player
from players.helpers import index_from_userid, userid_from_index,userid_from_edict,index_from_steamid
from threading import Thread

from paths import PLUGIN_DATA_PATH, GAME_PATH
from queue import Empty, Queue
import time

#SQL Alchemy
from sqlalchemy import Column, ForeignKey, Integer, String, Index, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql.expression import insert
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, desc


STATS_DATA_PATH = PLUGIN_DATA_PATH / 'scoreboard'
if not STATS_DATA_PATH.exists():
    STATS_DATA_PATH.makedirs()
CORE_DB_PATH = STATS_DATA_PATH / 'players.db'
CORE_DB_REL_PATH = CORE_DB_PATH.relpath(GAME_PATH.parent)

player_loaded = {}
output = Queue()
statsplayers = {}
player_session = {}
stats_screen = {}
stats_active = {}
stats_rank = {}

map_end_time = None
mp_timelimit = ConVar('mp_timelimit')

stats_button = PlayerButtons.SCORE

npc_list = ['npc_zombie',
    'npc_manhack',
    'npc_headcrab',
    'npc_antilion',
    'npc_antilionguard',
    'npc_clawscanner',
    'npc_combinedropship',
    'npc_combinegunship',
    'npc_crow',
    'combine_mine',
    'npc_headcrab_black',
    'npc_headcrab_fast',
    'npc_helicopter',
    'npc_hunter',
    'npc_ichthyosaur',
    'npc_ministriper',
    'npc_missildefense',
    'npc_mortarsynth',
    'npc_pigeon',
    'npc_poisonzombie',
    'npc_rollermine',
    'npc_sniper',
    'npc_stalker',
    'npc_strider',
    'npc_turret_ceiling',
    'npc_turret_floor',
    'npc_turret_ground',
    'npc_vortigaunt',
    'npc_zombie_torso',
    'npc_zombine'
]

@contextmanager
def session_scope():
	session = Session()
	try:
		yield session
		session.commit()
	except:
		session.rollback()
		raise
	finally:
		session.close()

# =============================================================================
# >> DATABASE
# =============================================================================    
Base = declarative_base()
engine = create_engine(f'sqlite:///{CORE_DB_REL_PATH}')
 
class Players(Base):
    __tablename__ = 'Players'
    UserID = Column(Integer,nullable=False,primary_key=True)
    steamid = Column(String(30),nullable=False)
    name = Column(String(30),nullable=False)
    kills = Column(Integer,default=0)
    deaths = Column(Integer,default=0)
    headshots = Column(Integer,default=0)
    suicides = Column(Integer,default=0)
    killstreak = Column(Integer,default=0)
    distance = Column(Float,default=0.0)
    npc_kills = Column(Integer,default=0)
    Index('playersIndex', steamid)

if not engine.dialect.has_table(engine, 'Players'):
    Base.metadata.create_all(engine)
    
Session = sessionmaker(bind=engine)


# =============================================================================
# >> LOAD
# =============================================================================	
def load():
    for player in PlayerIter():
        statsplayers[player.userid] = StatsPlayer(player.userid)
        init_player_session(player.userid)
    Delay(0.1,init_timeleft)
    _load_ranks()
    
    
def init_timeleft():
    global map_end_time
    timelimit = mp_timelimit.get_int() * 60
    map_end_time = time.time() + timelimit if timelimit else None
    
def _load_ranks():
    with session_scope() as session:
        query = session.query(Players).all()
        if query != None:
            for (user) in query:
                stats_rank[user.steamid] = {}
                stats_rank[user.steamid]['name'] = user.name
                stats_rank[user.steamid]['kills'] = user.kills
                stats_rank[user.steamid]['deaths'] = user.deaths
                stats_rank[user.steamid]['points'] = user.kills-user.deaths
                

        
# =============================================================================
# >> HELPERS
# =============================================================================	        
@Repeat
def repeat():
	try:
		callback = output.get_nowait()
	except Empty:
		pass
	else:
		callback()
repeat.start(0.1)

@Repeat
def show_stats_repeat():
    for player in PlayerIter('all'):
        if stats_screen[player.userid] == True:
            session_message = "Session Stats:\n\n"+"Points: "+str(player_session[player.userid]["kills"]-player_session[player.userid]["deaths"])+"\nKills: "+str(player_session[player.userid]["kills"])+"\nDeaths: "+str(player_session[player.userid]["deaths"])+"\nSuicides: "+str(player_session[player.userid]["suicides"])+"\nHeadshots: "+str(player_session[player.userid]['headshots'])+"\nKDR: "+str(calc_session_kdr(player_session[player.userid]["kills"],player_session[player.userid]["deaths"]))+"\nKillstreak: "+str(player_session[player.userid]["highest_killstreak"])+"\nNPC Kills: "+str(player_session[player.userid]["npc_kills"])
            HudMsg(
                message=session_message,
                x=0.01,
                y=-0.60,
                color1=GREEN,
                color2=GREEN,
                effect=0,
                fade_in=0.05,
                fade_out=0.1,
                hold_time=0.5,
                fx_time=1.0,
                channel=0,
            ).send(player.index)
            
            global_message = "Global Stats:\n\n"+"Points: "+str(statsplayers[player.userid].kills-statsplayers[player.userid].deaths)+"\nKills: "+str(statsplayers[player.userid].kills)+"\nDeaths: "+str(statsplayers[player.userid].deaths)+"\nSuicides: "+str(statsplayers[player.userid].suicides)+"\nHeadshots: "+str(statsplayers[player.userid].headshots)+"\nKDR: "+str(statsplayers[player.userid].calc_kdr(statsplayers[player.userid].kills,statsplayers[player.userid].deaths))+"\nKillstreak: "+str(statsplayers[player.userid].killstreak)+"\nNPC Kills: "+str(statsplayers[player.userid].npc_kills)
            HudMsg(
                message=global_message,
                x=0.85,
                y=-0.60,
                color1=GREEN,
                color2=GREEN,
                effect=0,
                fade_in=0.05,
                fade_out=0.1,
                hold_time=0.5,
                fx_time=1.0,
                channel=1,
            ).send(player.index)
            time_message = time.strftime('%a, %m.%y. %H:%M:%S',time.localtime(time.time()))
            HudMsg(
                message=time_message,
                x=-1,
                y=0.07,
                color1=GREEN,
                color2=GREEN,
                effect=0,
                fade_in=0.05,
                fade_out=0.1,
                hold_time=0.5,
                fx_time=1.0,
                channel=2,
            ).send(player.index)
            timeleft = map_end_time - time.time()
            minutes, seconds = divmod(timeleft, 60)
            timeleft_message = "Timeleft: %.0f minutes and %.0f seconds remaining." % (minutes,seconds)
            HudMsg(
                message=timeleft_message,
                x=-1,
                y=0.90,
                color1=GREEN,
                color2=GREEN,
                effect=0,
                fade_in=0.05,
                fade_out=0.1,
                hold_time=0.5,
                fx_time=1.0,
                channel=3,
            ).send(player.index)
        elif stats_active[player.userid] == True:
            for i in range(4):
                HudMsg(
                    message="",
                    x=0.01,
                    y=-0.88,
                    color1=GREEN,
                    color2=GREEN,
                    effect=0,
                    fade_in=0.05,
                    fade_out=0.5,
                    hold_time=0.5,
                    fx_time=1.0,
                    channel=i,
                ).send(player.index)
            stats_active[player.userid] = False
            
            
show_stats_repeat.start(0.1)


def exists(userid):
	try:
		index_from_userid(userid)
	except ValueError:
		return False
	return True
    
def exists_index(index):
    try:
        userid_from_index(index)
    except ValueError:
        return False
    return True
    

    
def init_player_session(userid):
    if userid not in player_session:
        player_session[userid] = {}
        player_session[userid]["kills"] = 0
        player_session[userid]["deaths"] = 0
        player_session[userid]["suicides"] = 0
        player_session[userid]["killstreak"] = 0
        player_session[userid]["highest_killstreak"] = 0
        player_session[userid]["headshots"] = 0
        player_session[userid]["npc_kills"] = 0
        
def calc_session_kdr(kills,deaths):
    if kills == 0: kills = 1
    if deaths == 0: deaths = 1
    return ("%.2f" % (kills/deaths))    

# =============================================================================
# >> PLAYER CLASS
# =============================================================================
class StatsPlayer(object):
    def __init__(self,userid):
        self.userid = int(userid)
        self.player_entity = Player.from_userid(self.userid)
        self.index = self.player_entity.index
        self.steamid = self.player_entity.uniqueid
        self.name = self.remove_warnings(self.player_entity.name)
            
        #Dict to check for load status
        player_loaded[self.userid] = False
        
        stats_screen[self.userid] = False
        stats_active[self.userid] = False
        
            
        #Player data
        self.UserID = -1
        self.points = 0
        self.kills = 0
        self.deaths = 0
        self.headshots = 0
        self.suicides = 0
        self.kdr = 0.0
        self.killstreak = 0
        self.distance = 0.0
        self.npc_kills = 0
        
        Thread(target=self._load_from_database).start()
        
    def _load_from_database(self):
        with session_scope() as session:
            #Player data
    
            player = session.query(Players).filter(Players.steamid==self.steamid).one_or_none()
            if player is None:
                player = Players(steamid=self.steamid,name=self.name)
                session.add(player)
                session.commit()
            self.UserID = player.UserID
            self.kills = player.kills
            self.deaths = player.deaths
            self.headshots = player.headshots
            self.suicides = player.suicides
            self.killstreak = player.killstreak
            self.distance = player.distance
            self.points = self.kills-self.deaths
            self.kdr = self.calc_kdr(self.kills,self.deaths)
            self.npc_kills = player.npc_kills
            _load_ranks()
            
        output.put(self._on_finish)
        
    def _on_finish(self):
        if exists(self.userid):
            OnPlayerLoaded.manager.notify(self)    
            
    def save(self):
        if exists(self.userid):        
            Thread(target=self._save_player_to_database).start()
        
    def _save_player_to_database(self):
        with session_scope() as session:
            player = session.query(Players).filter(Players.UserID==self.UserID).one_or_none()
            player.steamid = self.steamid
            player.name = self.name
            player.kills = self.kills
            player.deaths = self.deaths
            player.headshots = self.headshots
            player.suicides = self.suicides
            player.killstreak = self.killstreak
            player.distance = self.distance
            player.npc_kills = self.npc_kills
            
            session.commit()
            
        output.put(self._on_player_saved)
        
    def _on_player_saved(self):
        if exists(self.userid):
            OnPlayerSaved.manager.notify(self)        
        
    def remove_warnings(self, value):
        return str(value).replace("'", "").replace('"', '')
        
    def calc_kdr(self,kills,deaths):
        if kills == 0: kills = 1
        if deaths == 0: deaths = 1
        return ("%.2f" % (kills/deaths))
        
        
for player in PlayerIter('all'):
    statsplayers[player.userid] = StatsPlayer(player.userid)
    init_player_session(player.userid)
        
# =============================================================================
# >> LISTENERS
# =============================================================================	
class OnPlayerSaved(ListenerManagerDecorator):
	manager = ListenerManager()
	
class OnPlayerLoaded(ListenerManagerDecorator):
	manager = ListenerManager()
    
@OnPlayerLoaded
def on_loaded(statsplayer):
    player_loaded[statsplayer.userid] = True
    
@OnPlayerRunCommand
def _on_player_run_command(player, usercmd):
    if player.is_bot():
        return
    if usercmd.buttons & stats_button:
        stats_screen[player.userid] = True
        stats_active[player.userid] = True
    else:
        stats_screen[player.userid] = False
        
@OnLevelInit
def level_init(map_name=None):
    global map_end_time
    timelimit = mp_timelimit.get_int() * 60
    map_end_time = time.time() + timelimit if timelimit else None
    for player in PlayerIter('all'):
        statsplayers[player.userid].save()
       
@OnClientActive
def on_client_active(index):
    statsplayers[Player(index).userid] = StatsPlayer(Player(index).userid)
    init_player_session(userid_from_index(index))

# =============================================================================
# >> EVENTS
# =============================================================================
@Event('player_disconnect')	
def player_disconnect(ev):
	userid = ev.get_int('userid')
	player_entity = Player(index_from_userid(userid))
	
	statsplayers[ev['userid']].save()
	if userid in statsplayers:
		statsplayers[ev['userid']].name = statsplayers[ev['userid']].remove_warnings(player_entity.name)
		statsplayers[ev['userid']].save()
        
@Event('player_hurt')
def player_hurt(ev):
    if ev['attacker'] != 0:
        attacker = Player.from_userid(ev['attacker'])
        victim = Player.from_userid(ev['userid'])
        if victim.hitgroup == HitGroup.HEAD:
            player_session[attacker.userid]["headshots"] += 1
            statsplayers[attacker.userid].headshots += 1        
        
        
@Event('player_death')
def player_death(ev):
    victim_userid = ev['userid']
    attacker_userid = ev['attacker']
    victim = Player.from_userid(ev['userid'])
    if ev['attacker'] != 0:
        attacker = Player.from_userid(ev['attacker'])
        if victim.userid != attacker.userid:
            statsplayers[attacker.userid].kills += 1
            player_session[attacker.userid]["kills"] += 1
            
            player_session[attacker.userid]["killstreak"] += 1
            if player_session[attacker.userid]["killstreak"] > statsplayers[attacker.userid].killstreak:
                statsplayers[attacker.userid].killstreak = player_session[attacker.userid]["killstreak"]
            if player_session[attacker.userid]["killstreak"] > player_session[attacker.userid]["highest_killstreak"]:
                player_session[attacker.userid]["highest_killstreak"] = player_session[attacker.userid]["killstreak"]            
            
            statsplayers[victim.userid].deaths += 1
            player_session[victim.userid]["deaths"] += 1
            
            if player_session[victim.userid]["killstreak"] > player_session[victim.userid]["highest_killstreak"]:
                player_session[victim.userid]["highest_killstreak"] = player_session[victim.userid]["killstreak"]
            player_session[victim.userid]["killstreak"] = 0
            
            stats_rank[attacker.uniqueid]['points'] = statsplayers[attacker.userid].kills-statsplayers[attacker.userid].deaths        
            stats_rank[victim.uniqueid]['points'] = statsplayers[victim.userid].kills-statsplayers[victim.userid].deaths
        else:
            statsplayers[victim.userid].suicides += 1
            player_session[victim.userid]["suicides"] += 1
            
            statsplayers[victim.userid].deaths += 1
            player_session[victim.userid]["deaths"] += 1
            
            player_session[victim.userid]["killstreak"] = 0
            
            stats_rank[victim.uniqueid]['points'] = statsplayers[victim.userid].kills-statsplayers[victim.userid].deaths
            
@Event('entity_killed')
def npc_killed(event):
    if exists_index(event['entindex_attacker']):
        classname = BaseEntity(event['entindex_killed']).classname
        if classname in npc_list:
            player = Player(event['entindex_attacker'])
            player_session[player.userid]["npc_kills"] += 1
            statsplayers[player.userid].npc_kills += 1
        
        
# =============================================================================
# >> CLIENTCOMMANDS
# =============================================================================       
@ClientCommand('rank')
@SayCommand('rank')
def rank_command(command, index, team_only=False):
    player = Player(index)
    rank_list = stats_rank.values()
    rank_list = sorted(stats_rank, key=lambda x: stats_rank[x]['points'],reverse=True)
    i = 0
    for x in rank_list:
        i+=1
        if player.uniqueid == x:
            rank = i
            break
    SayText2("\x04[Stats]\x03 Your rank is \x04%s \x03of \x04%s \x03with \x04%s \x03points." % (i, len(rank_list),stats_rank[player.uniqueid]['points'])).send(index)

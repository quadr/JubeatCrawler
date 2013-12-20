# -*- coding: utf-8 -*-
import redis
import httplib2
import urllib
import Cookie
import time
import gevent
import logging
import unicodedata
import collections
from gevent import monkey
from datetime import datetime, timedelta
from BeautifulSoup import BeautifulSoup
import sys, traceback

monkey.patch_all(thread=False)

playScoreUrl = 'http://p.eagate.573.jp/game/jubeat/saucer/p/playdata/music.html?rival_id=%d&page=%d'
musicPageUrl = 'http://p.eagate.573.jp/game/jubeat/saucer/p/playdata/music_detail.html?rival_id=%d&mid=%d'
playHistoryUrl = 'http://p.eagate.573.jp/game/jubeat/saucer/p/playdata/history.html?rival_id=%d&page=%d'
contestListUrl = 'http://p.eagate.573.jp/game/jubeat/saucer/p/contest/join_info.html?s=1&rival_id=%d'
contestDataUrl = 'http://p.eagate.573.jp/game/jubeat/saucer/p/contest/detail.html?contest_id=%d'
playerInfoUrl = 'http://p.eagate.573.jp/game/jubeat/saucer/p/playdata/index_other.html?rival_id={0}'

def getRedis():
  return redis.Redis(db=11)

def now():
  return datetime.now().strftime('%Y/%m/%d %H:%M:%S')

def dateToTime(date):
  return int(time.mktime(datetime.strptime(date, '%Y/%m/%d %H:%M:%S').timetuple()))

def unescape(html):
  html = html.replace(u'&lt;', u'<')
  html = html.replace(u'&gt;', u'>')
  html = html.replace(u'&apos;', u"'")
  html = html.replace(u'&quot;', u'"')
  html = html.replace(u'&nbsp;', u' ')
  html = html.replace(u'&amp;', u'&')
  return html

RankBase = [
  (500000, "E"),
  (700000, "D"),
  (800000, "C"),
  (850000, "B"),
  (900000, "A"),
  (950000, "S"),
  (980000, "SS"),
  (1000000, "SSS"),
  (1000001, "EXC")
]

IRCColor = {
  'white': u'\u000300',
  'black': u'\u000301',
  'dark_blue': u'\u000302',
  'dark_green': u'\u000303',
  'light_red': u'\u000304',
  'dark_red': u'\u000305',
  'magenta': u'\u000306',
  'orange': u'\u000307',
  'yellow': u'\u000308',
  'light_green': u'\u000309',
  'cyan': u'\u000310',
  'light_cyan': u'\u000311',
  'light_blue': u'\u000312',
  'light_magenta': u'\u000313',
  'gray': u'\u000314',
  'light_gray': u'\u000315',
  'reset': u'\u000f'
}

RankColor = {
  "E" : IRCColor['gray'],
  "D" : IRCColor['gray'],
  "C" : IRCColor['dark_red'],
  "B" : IRCColor['light_red'],
  "A" : IRCColor['light_blue'],
  "S" : IRCColor['dark_green'],
  "SS" : IRCColor['cyan'],
  "SSS" : IRCColor['light_green'],
  "EXC" : IRCColor['yellow'] + u',01'
}

LvColor = {
  "BASIC" : IRCColor['dark_green'],
  "ADVANCED" : IRCColor['orange'],
  "EXTREME" : IRCColor['dark_red'],
  "EDIT" : IRCColor['light_blue']
}

DifficultyShortString = {
  "BASIC" : "BSC",
  "ADVANCED" : "ADV",
  "EXTREME" : "EXT",
  "EDIT" : "EDIT"
}

def getRank(score):
  for rb in RankBase:
    if score < rb[0]:
      return rb[1]

MusicInfo = collections.namedtuple('MusicInfo', ['title', 'artist', 'difficulty', 'bpm', 'lv', 'notes'])

DifficultyString = ["BASIC", "ADVANCED", "EXTREME", "EDIT"]

def parseMusicInfo(raw):
  s = raw.split("\t")
  ret = []
  if len(s) == 1:
    return ret
  for i in xrange(0,3):
    ret.append(MusicInfo(
      title      = s[0],
      artist     = s[1],
      difficulty = DifficultyString[i],
      bpm        = s[2],
      lv         = int(s[i+3]),
      notes      = int(s[i+6])))
  return ret

def makeMusicInfoList():
  rawLines = open('list.txt', 'r').read().decode('utf-8').split('\n')
  musicList = []
  for rawLine in rawLines:
    musicList += parseMusicInfo(rawLine)
  return musicList

MusicInfoList = makeMusicInfoList()
MusicNoteDict = dict(map(lambda m: ((m.title,m.difficulty), m.notes), MusicInfoList))

def initMusicTable(rival_id):
    r = getRedis() 
    scores = r.hgetall('score:%s'%rival_id)
    ret = r.hmset('music_id', dict((k, int(v.split(':')[0])) for k,v in scores.iteritems()))
    logging.info('Init Music Table Finished')
    return ret

def syncMusicID(rival_id):
    r = getRedis()
    scores = r.hgetall('score:%s'%rival_id)
    if len(scores) == 0:
        getUserScore(rival_id)
        return {}
    else:
        ret = r.hmset('score:%s'%rival_id, dict((k, str(r.hget('music_id', k)) + ':' + v.split(':', 1)[1]) for k,v in scores.iteritems()))
        logging.info('Sync Music Id Finished')
        return ret

# example of raw : "5733600:[996029, 994097, 958275]:[True, True, False]"
def parseScoreInfo(raw):
    s = raw.split(':')
    ret = {
        'id'    : s[0],
        'score' : [ int(_) for _ in s[1][1:-1].replace(' ', '').split(',') ],
        'fc'    : [ _ == 'True' for _ in s[2][1:-1].replace(' ', '').split(',')]
    }
    return ret

# example: calcConvertedScore('only my railgun', 'EXTREME', 999031) -> 0.600
def calcConvertedScore(title, difficulty, score):
  key = (title,difficulty)
  if key in MusicNoteDict:
    return (1000000 - score) * MusicNoteDict[key] / 900000.0

def newScore(title):
    r = getRedis()
    music_id = r.hget('music_id', title)
    return str(music_id) + ':' + str([0, 0, 0]) + ':' + str([False, False, False])

# example: calcUpdatedScore(57710029539329, 'only my railgun', 'EXTREME', 999031) -> -969
# Also updates the db if best score is changed
def calcUpdatedScore(rival_id, title, difficulty, score):
    if difficulty == 'BASIC': i = 0
    elif difficulty == 'ADVANCED': i = 1
    else: i = 2

    r = getRedis()

    user_name = r.hget("rival_id", rival_id).decode('utf-8')
    if not r.exists('score:%d'%rival_id):
        return '?'
    raw = r.hget('score:%d'%rival_id, title)
    if raw is None:
        # if there is no score data, then make a new one
        r.hset('score:%d'%rival_id, title, newScore(title))
        raw = r.hget('score:%d'%rival_id, title)
        if raw is None:
            return '?'

    prev = parseScoreInfo(raw)
    prev_score = prev['score'][i]
    if score == 1000000:
        prev['fc'][i] = True

    result = score - prev_score
    if result > 0:
        prev['score'][i] = score
        r.hset('score:%d'%rival_id, title, '%(id)s:%(score)s:%(fc)s'%prev)
        logging.info(user_name + ' updated score of [' + title + ']')
        return '+' + str(result)
    elif result < 0:
        return '-' + str(0 - result)
    else:
        return '0'

def getHttpContents(url):
  try:
    http = httplib2.Http()
    r = getRedis()
    if not r.exists('cookie'):
      if not login():
        return None

    res, c = http.request(url, headers={'cookie':r.get('cookie')})
    if 'err' in res['content-location'] or 'REDIRECT' in res['content-location']:
      logging.error('getHttpContents : %s'%url)
      return None
    s = BeautifulSoup(c.decode('shift_jisx0213'))
    if s.find('a', attrs={'class': 'login'}) is not None:
      r.delete('cookie')
      login()
    return s
  except Exception, e:
    logging.error('getHttpContents : %s %s'%(url, e))
  
  return None

def login(kid=None, password=None):
  http = httplib2.Http()

  r = getRedis()
  if r.exists('cookie'):
    return True
  
  if kid is not None and password is not None:
    r.hmset('auth_info', {'KID':kid, 'pass':password})
  
#  loginUrl = 'https://p.eagate.573.jp/gate/p/login.html'
#  res, c = http.request(loginUrl)
  loginUrl = 'https://p.eagate.573.jp/gate/p/login.html'
  loginHeader = { 'content-type' : 'application/x-www-form-urlencoded', 'Origin': 'https://p.eagate.573.jp', 'Referer': 'https://p.eagate.573.jp/gate/p/login.html', 'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/28.0.1500.72 Safari/537.36'  }
  auth_info = r.hgetall('auth_info')
  auth_info['OTP'] = ''
  params = urllib.urlencode(auth_info)
  res, c = http.request(loginUrl, 'POST', params, headers=loginHeader)
  if res.status == 302 :
    logging.info('login success')
    cookie = Cookie.SimpleCookie(res['set-cookie']).values()[0].OutputString(attrs=[])
    expires = Cookie.SimpleCookie(res['set-cookie']).values()[0]['expires']
    expire_date = datetime.strptime(expires, '%a, %d-%b-%Y %H:%M:%S %Z') + timedelta(hours=9)
    r.set('cookie', cookie)
    r.expireat('cookie', int(time.mktime(expire_date.timetuple())))
    return True
  else:
    logging.error('login failed')
    return False

def getContestPeriod(unicode_date):
  date = [ datetime.strptime(_.encode('utf-8').strip(), u'%m月%d日 %H時'.encode('utf-8')) for _ in unicode_date.split(u'〜') ]
  year = [ datetime.now().year, datetime.now().year ]
  if date[0].month > datetime.now().month:
    year[0] -= 1
  if date[0] > date[1]:
    year[1] += 1
  return [ datetime(y, d.month, d.day, d.hour).strftime('%Y/%m/%d %H:%M:%S') for y, d in zip(year, date) ] 

def updateContestInfo(rival_id):
  try:
    r = getRedis()
    
    c = getHttpContents(contestListUrl%rival_id)
    if c is None:
      return
    
    table = c.find(id='contest_list')
    if table is None:
      return
    rows = table.findAll('tr')
    for row in rows:
      cs = row.findAll('td')
      if len(cs) == 0:
        continue
      contest_info = dict(zip(['name', 'id', 'owner'], [ _.text for _ in cs[:3]]))
      contest_info.update(dict(zip(['start', 'end'], getContestPeriod(cs[3].text))))
      if r.hexists('ignore_contest', contest_info['id']):
        continue
      key = 'contest_info:' + contest_info['id']
      if not r.exists(key):
        r.hmset(key, contest_info)
        if now() >= contest_info['start'] and now() <= contest_info['end']:
          cur_key = 'current_contest:' + contest_info['id']
          r.set(cur_key, 1)
          r.expireat(cur_key, dateToTime(contest_info['end'])+600)

  except Exception, e:
    logging.error('updateContestInfo Error: %s(%d)'%(e, rival_id))
    return

def updateContestData(contest_id):
  try:
    c = getHttpContents(contestDataUrl%contest_id)
    if c is None:
      return set()
    
    r = getRedis()
    members_key = 'contest_members:%d'%contest_id
    music_list_key = 'music_list:%d'%contest_id
    if not r.exists(music_list_key):
      table = c.find(id='contest_theme')
      rows = table.findAll('tr', attrs={'class':'theme'})
      for row in rows:
        cols = row.findAll('td')
        music_title = unescape(cols[1].text)
        difficulty = DifficultyString[int(cols[2].find('img')['alt'])]
        music = music_title + ':' + difficulty
        r.rpush(music_list_key, music)

    rows = c.find(id='contest_ranking').findAll('a')
    for row in rows:
      rival_id = row['href'][row['href'].index(u'=')+1:]
      r.hset('rival_id', rival_id, row.text)
      r.sadd(members_key, rival_id)

    members = r.smembers(members_key)
    if members is None:
      return set()

    return members

  except Exception, e:
    logging.error('getContestData Error: %s(%d)'%(e, contest_id))
    return set()

def getMusicScorePage(url):
  for i in xrange(10):
    c = getHttpContents(url)
    if c is not None and c.find(id='play_music_table'):
      return c
    music_data = c.find(id='music_data')
    if music_data and u'公開' in music_data.text:
      return None
    gevent.sleep(4)
  return None
  

def getUserScore(rival_id):
  try:
    r = getRedis()
    user_name = r.hget('rival_id', rival_id).decode('utf-8')

    logging.info("Getting scores of %s(%d)"%(user_name, rival_id))
    c = getMusicScorePage(playScoreUrl%(rival_id, 1))
    if c is None:
      logging.error("getUserScore Error: site is not availabe. (1)")
      return []


    playScore = []
    hashData = {}
    pages = []
    page_indice = c.find(attrs={"class":"pager"}).findAll(attrs={"class":"number"})
    for page_index in page_indice:
      idx = int(page_index.text)
      page = None
      if idx == 1:
        page = c
      else:
        page = getMusicScorePage(playScoreUrl%(rival_id, idx))
      if page is None:
        logging.error("getUserScore Error: site is not availabe.({0})".format(idx))
        return []
      pages.append(page)


    for page in pages:
        oddrows = page.findAll(attrs={"class":"odd"})
        evenrows = page.findAll(attrs={"class":"even"})
        rows = oddrows + evenrows
        
        #scoredata : music, bsc_score, bsc_fc, adv_score, adv_fc, ext_score, ext_fc
        for row in rows:
            #bsc adv ext
            scores = [(row.contents[5]), row.contents[7], row.contents[9]]
            scoredata = {}
            scoredata['music'] = unescape(row.find('td', attrs={'class':'mname'}).find('a').text)
            scoredata['music_id'] = row.find('td', attrs={'class':'mname'}).find('a')['href'][-8:]
            scoredata['score'] = []
            scoredata['fc'] = []
            
            for score in scores:
                if score.text == "-":
                    scoredata['score'].append(0)
                else:
                    scoredata['score'].append(int(score.text))
                scoredata['fc'].append(int(score.find('div')['class'][-1]) == 1)
            playScore.append(scoredata)
            hashData[scoredata['music']] = scoredata['music_id'] + ':' + str(scoredata['score']) + ':' + str(scoredata['fc'])

    score_key = 'score:%d'%rival_id
    map(lambda _: logging.info(user_name + u'%(music)s + %(score)s + %(fc)s'%_), playScore)
    r.hmset(score_key, hashData)

    r.lpush('IRC_HISTORY', u'\u0002[%s]님의 스코어가 업데이트 되었습니다.'%(user_name))
    
  except Exception, e:
    traceback.print_exc(file=sys.stdout)
    logging.error('getUserScore Error: %s(%d)'%(e, rival_id))
    return []

def getUserHistory(rival_id):
  try:
    r = getRedis()
    last_update = r.hget('last_update', rival_id)
    update_date = last_update
    user_name = r.hget('rival_id', rival_id).decode('utf-8')

    playHistory = []
    up_to_date = False
    c = getHttpContents(playHistoryUrl%(rival_id, 1))
    pages = c.find(attrs={"class":"pager"}).findAll(attrs={"class":"number"})
    for page in pages:
      i = int(page.text)
      c = getHttpContents(playHistoryUrl%(rival_id, i))
      if c is None:
        return []
      
      rows = c.findAll(attrs={'class':'history_container2'})

      # Being 만세!
      if len(rows) == 0:
        return []

      for row in rows:
        playdata = {}
        playdata['date'] = row.find(attrs={'class':'data1_info'}).text[6:25]
        playdata['place'] = unicodedata.normalize('NFKC', row.find(attrs={'class':'data1_info'}).text[32:])
        playdata['music'] = unescape(row.find(attrs={'class':'result_music'}).find('a').text)
        playdata['difficulty'] = DifficultyString[int(row.find(attrs={'class':'level'}).find('img')['src'][-5:-4])]
        playdata['score'] = row.findAll('li')[-1].text.split('/')[0]
        if update_date is None or update_date < playdata['date']:
          update_date = playdata['date']
        if last_update and last_update >= playdata['date']:
          up_to_date = True
          break

        music_id = r.hget('music_id', playdata['music'])
        if music_id is None:
            new_id = int(row.find(attrs={'class':'result_music'}).find('a').get('href')[-8:])
            r.hset('music_id', playdata['music'], new_id)
        playHistory.append(playdata)

      if up_to_date:
        break
    
    playHistory.reverse()
    history_key = 'history:%d'%rival_id
    map(lambda _: logging.info(user_name + ' %(date)s %(music)s %(difficulty)s %(score)s %(place)s'%_), playHistory)
    for row in playHistory :
      score = int(row["score"])
      difficulty = row["difficulty"]
      rank = getRank(score)
      updatedScore = '0'
      convertedScore = None
      if difficulty != "EDIT":
        convertedScore = calcConvertedScore(row['music'], difficulty, score)
        updatedScore = calcUpdatedScore(rival_id, row['music'], difficulty, score)
      if updatedScore[0] == '+':
          updatedScore = IRCColor['light_red'] + updatedScore + RankColor[rank]
      elif updatedScore[0] == '-':
          updatedScore = IRCColor['dark_blue'] + updatedScore + RankColor[rank]
      if convertedScore is not None:
        convertedScore = convertedScore / 0.3
      if convertedScore is not None or convertedScore > 0:
        r.lpush('IRC_HISTORY', u'\u0002[%s] %s%s (%s)\u000f - %s%d (%.2f/%s)\u000f - \u0002%s - %s'%(user_name, LvColor[difficulty], row['music'], DifficultyShortString[difficulty], RankColor[rank], score, convertedScore, updatedScore, row['date'], row['place']))
      else:
        r.lpush('IRC_HISTORY', u'\u0002[%s] %s%s (%s)\u000f - %s%d (%s)\u000f - \u0002%s - %s'%(user_name, LvColor[difficulty], row['music'], DifficultyShortString[difficulty], RankColor[rank], score, updatedScore, row['date'], row['place']))
      if score == 1000000:
        r.lpush('IRC_HISTORY', u'\u0002[알림] %s님이 %s%s (%s)\u000f\u0002를 %sEXCELLENT\u000f \u0002했습니다!!'%(user_name, LvColor[difficulty], row['music'], DifficultyShortString[difficulty], RankColor["EXC"]))
      elif convertedScore is not None and int(round(convertedScore)) <= 2:
        r.lpush('IRC_HISTORY', u'\u0002[알림] %s님이 %s%s (%s)\u000f\u0002를 %s%dgr\u000f \u0002했습니다. orz'%(user_name, LvColor[difficulty], row['music'], DifficultyShortString[difficulty], RankColor["EXC"], int(round(convertedScore))))

    if update_date:
      r.hset('last_update', rival_id, update_date)
    map(lambda _: r.lpush(history_key, '%(date)s:%(music)s:%(difficulty)s:%(score)s'%_), playHistory)
    map(lambda _: r.lpush('recent_history', '%(date)s\t%(music)s\t%(difficulty)s\t%(score)s\t%(place)s'%_+'\t'+user_name+'\t'+now()), playHistory) 
    return [ ((u'%(date)s:%(music)s:%(difficulty)s:%(score)s:{0}'.format(rival_id)%_).encode('utf-8'), (u'%(music)s:%(difficulty)s'%_).encode('utf-8'), int(_['score']), _['date'].encode('utf-8')) for _ in playHistory ]

  except Exception, e:
    traceback.print_exc(file=sys.stdout)
    logging.error('getUserHistory Error: %s(%d)'%(e, rival_id))
    return []

def updateContestHistory():
  try:
    r = getRedis()
    
    current_contest_list = [ int(_[16:]) for _ in r.keys('current_contest:*') ]
    jobs = [ gevent.spawn(updateContestData, contest_id) for contest_id in current_contest_list ]
    gevent.joinall(jobs)
    
    contest_members = dict(zip(current_contest_list, [ job.value for job in jobs ]))

    member_list = r.hgetall('rival_id')
    [ getUserScore(int(rival_id)) for rival_id in member_list.iterkeys() if not r.exists(('score:%s'%rival_id)) ]
    jobs = [ gevent.spawn(getUserHistory, int(rival_id)) for rival_id, user in member_list.iteritems() ]
    gevent.joinall(jobs)
    
    playdata = dict(zip(member_list.keys(), [ _.value for _ in jobs ]))
    r.ltrim('recent_history', 0, 200)

    for contest_id, members in contest_members.iteritems():
      contest_history_key = 'contest_history:{0}'.format(contest_id)
      contest_records_key = 'contest_records:{0}'.format(contest_id)
      contest_info_key = 'contest_info:{0}'.format(contest_id)
      
      contest_info = r.hgetall(contest_info_key)
      music_list = r.lrange('music_list:{0}'.format(contest_id), 0, -1)
      
      logging.info('update contest <{0}>'.format(contest_info['name']))
      update_users = filter(lambda _: (_ in playdata and len(playdata[_]) is not 0) or (not r.hexists(contest_records_key, _)), members)
      contest_history = []
      for user in update_users:
        user_record = r.hget(contest_records_key, user)
        if user_record is None:
          user_record = [ 0 for i in music_list ]
        else:
          user_record = [ int(score) for score in user_record.split(':') ]
        for data in playdata[user]:
          if data[1] in music_list and data[3] >= contest_info['start'] and data[3] <= contest_info['end'] :
            idx = music_list.index(data[1])
            contest_history.append(data[0])
            user_record[idx] = max(user_record[idx], data[2])
        r.hset(contest_records_key, user, ':'.join([str(_) for _ in user_record]))
      contest_history.sort()
      logging.info('add {0} histories'.format(len(contest_history)))
      map(lambda _: r.lpush(contest_history_key, _), contest_history)
      r.hset('contest_info:{0}'.format(contest_id), 'last_update', now())

  except Exception, e:
    logging.error('updateContestHistory Error: %s'%e)
    return

def registerUser(rival_id, user_name, update_contest=True, update_score=True):
  try:
    r = getRedis()
    user_name = user_name.upper()
    
    if r.hexists('rival_id', rival_id):
      if user_name != r.hget('rival_id', rival_id):
        logging.error('user_name does not matched : {0}, {1}'.format(user_name, r.hget('rival_id', rival_id)))
        return False
      logging.info('user already exist : {0}, {1}'.format(rival_id, r.hget('rival_id', rival_id)))
      return True

    c = getHttpContents(playerInfoUrl.format(rival_id))
    if c is None:
      logging.error('registerUser error : site is not available')
      return False
    
    user_name_site = c.find(id='pname').findAll('span')[-1].text
    if user_name_site != user_name:
      logging.error('registerUser error : name missmatched {0}, {1}'.format(user_name, user_name_site))
      return False

    r.hset('rival_id', rival_id, user_name)
    
    if update_contest:
      updateContestInfo(int(rival_id))

    if update_score:
      getUserScore(int(rival_id))

    return True

  except Exception, e:
    logging.error('updateContestHistory Error: %s'%e)
    return False

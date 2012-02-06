# -*- coding: utf-8 -*-
import redis
import httplib2
import urllib
import Cookie
import time
import gevent
import logging
from gevent import monkey
from datetime import datetime, timedelta
from BeautifulSoup import BeautifulSoup

monkey.patch_all(thread=False)

playHistoryUrl = 'http://p.eagate.573.jp/game/jubeat/copious/p/playdata/history.html?rival_id=%d&page=%d'
contestListUrl = 'http://p.eagate.573.jp/game/jubeat/copious/p/contest/contest2.html?s=1&rival_id=%d'
contestDataUrl = 'http://p.eagate.573.jp/game/jubeat/copious/p/contest/detail.html?rally_id=%d'

def getRedis():
  return redis.Redis(db=12)

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
    return BeautifulSoup(c)
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
  
  loginUrl = 'https://p.eagate.573.jp/gate/p/login.html'
  res, c = http.request(loginUrl)
  cookie = Cookie.SimpleCookie(res['set-cookie']).values()[0].OutputString(attrs=[])
  expires = Cookie.SimpleCookie(res['set-cookie']).values()[0]['expires']
  loginUrl = 'https://p.eagate.573.jp/gate/p/login.html'
  loginHeader = { 'content-type' : 'application/x-www-form-urlencoded', 'cookie': cookie }
  params = urllib.urlencode(r.hgetall('auth_info'))
  res, c = http.request(loginUrl, 'POST', params, headers=loginHeader)
  if res.status == 302 :
    logging.info('login success')
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
  if date[0].month < datetime.now().month:
    year[0] -= 1
    year[1] -= 1
  if date[0] > date[1]:
    year[1] += 1
  return [ datetime(y, d.month, d.day, d.hour).strftime('%Y/%m/%d %H:%M:%S') for y, d in zip(year, date) ] 

def updateContestInfo(rival_id):
  try:
    r = getRedis()
    
    c = getHttpContents(contestListUrl%rival_id)
    if c is None:
      return
    
    table = c.find(id='contest_search_result')
    if table is None:
      return
    rows = table.findAll('tr')
    for row in rows:
      cs = row.findAll('td')
      if len(cs) == 0:
        continue
      contest_info = dict(zip(['name', 'id', 'owner'], [ _.text for _ in cs[:3]]))
      contest_info.update(dict(zip(['start', 'end'], getContestPeriod(cs[3].text))))
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
      rows = table.findAll('tr')[1:]
      for row in rows:
        music = ':'.join(map(lambda _: unescape(_.text), row.findAll('td'))[1:3])
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

def getUserHistory(rival_id):
  try:
    r = getRedis()
    
    last_update = r.hget('last_update', rival_id)
    update_date = None
    user_name = r.hget('rival_id', rival_id)

    playHistory = []
    up_to_date = False
    for i in xrange(6):
      c = getHttpContents(playHistoryUrl%(rival_id, i+1))
      if c is None:
        return []
      
      rows = c.findAll(attrs={'class':'history_box'})
      for row in rows:
        playdata = {}
        playdata['date'] = row.find(attrs={'class':'hitory_data'}).text[6:25]
        playdata['music'] = unescape(row.find(attrs={'class':'ht_mtitle'}).text)
        playdata['difficulty'] = row.find(attrs={'class':'ht_level'}).text
        playdata['score'] = row.findAll('li')[-1].text.split('/')[0]
        if update_date is None:
          update_date = playdata['date']
        if last_update and last_update >= playdata['date']:
          up_to_date = True
          break
        playHistory.append(playdata)

      if up_to_date:
        break
    
    playHistory.reverse()
    history_key = 'history:%d'%rival_id
    map(lambda _: r.lpush(history_key, '%(date)s:%(music)s:%(difficulty)s:%(score)s'%_), playHistory)
    map(lambda _: logging.info(user_name + ' %(date)s %(music)s %(difficulty)s %(score)s'%_ ), playHistory)
    if update_date:
      r.hset('last_update', rival_id, update_date)
    return [ ((u'%(date)s:%(music)s:%(difficulty)s:%(score)s:{}'.format(rival_id)%_).encode('utf-8'), (u'%(music)s:%(difficulty)s'%_).encode('utf-8'), int(_['score']), _['date'].encode('utf-8')) for _ in playHistory ]

  except Exception, e:
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
    jobs = [ gevent.spawn(getUserHistory, int(rival_id)) for rival_id, user in member_list.iteritems() ]
    gevent.joinall(jobs)
    
    playdata = dict(zip(member_list.keys(), [ _.value for _ in jobs ]))

    for contest_id, members in contest_members.iteritems():
      contest_history_key = 'contest_history:{}'.format(contest_id)
      contest_records_key = 'contest_records:{}'.format(contest_id)
      contest_info_key = 'contest_info:{}'.format(contest_id)
      
      contest_info = r.hgetall(contest_info_key)
      music_list = r.lrange('music_list:{}'.format(contest_id), 0, -1)
      
      logging.info('update contest <{}>'.format(contest_info['name']))
      update_users = filter(lambda _: _ in playdata and len(playdata[_]) is not 0, members)
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
      logging.info('add {} histories'.format(len(contest_history)))
      map(lambda _: r.lpush(contest_history_key, _), contest_history)
      r.hset('contest_info:{}'.format(contest_id), 'last_update', now())

  except Exception, e:
    logging.error('updateContestHistory Error: %s'%e)
    return

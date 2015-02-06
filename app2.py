from flask import Flask, request, session, g, redirect, url_for, abort, render_template, flash, jsonify, current_app
from datetime import datetime, tzinfo, timedelta
import redis
import sys
import PyRSS2Gen
import base64, json
from functools import wraps
from gevent import monkey

monkey.patch_all()

app = Flask(__name__)
def getRedis():
  return redis.Redis(db=11)

def strToUTC(s):
  return datetime.strptime(s, '%Y/%m/%d %H:%M:%S')-timedelta(hours=9)

def jsonp(func):
  @wraps(func)
  def decorated_function(*args, **kwargs):
    callback = request.args.get('callback', False)
    if callback:
      data = str(func(*args,**kwargs).data)
      content = '{0}({1})'.format(str(callback), data)
      mimetype = 'application/javascript'
      return current_app.response_class(content, mimetype=mimetype)
    else:
      return func(*args, **kwargs)
  return decorated_function

@app.route('/contest')
@jsonp
def contest_list():
  try:
    r = getRedis()
    current_contest_list = [ r.hgetall('contest_info:{0}'.format(_[16:])) for _ in r.keys('current_contest:*') ]
    return jsonify(current_contest_list=current_contest_list, code='ok')
  except Exception, e:
    print sys.exc_info()[0], e
    return jsonify(code='error')

@app.route('/contest/all')
@jsonp
def contest_list_all():
  try:
    r = getRedis()
    contest_list = [ r.hgetall(_) for _ in r.keys('contest_info:*') ]
    return jsonify(contest_list=contest_list, code='ok')
  except Exception, e:
    print sys.exc_info()[0], e
    return jsonify(code='error')


@app.route('/contest/<contest_id>')
@jsonp
def contest(contest_id):
  try:
    r = getRedis()

    contest_info_key = 'contest_info:{0}'.format(contest_id)
    contest_member_key = 'contest_members:{0}'.format(contest_id)
    contest_records_key = 'contest_records:{0}'.format(contest_id)
    music_list_key = 'music_list:{0}'.format(contest_id)
    if not r.exists(contest_info_key):
      return jsonify(code='nodata')
    contest_info = r.hgetall(contest_info_key)
    members = r.smembers(contest_member_key)
    members = dict(zip(members, [r.hget('rival_id', rival_id) for rival_id in members]))
    records = r.hgetall(contest_records_key)
    music_list = [ key.split(':') for key in r.lrange(music_list_key, 0, -1) ]
    user_records = {}
    for rival_id, scores in records.iteritems():
      record = {}
      record['scores'] = scores.split(':')
      record['last_played'] = r.hget('last_update', rival_id)
      record['rival_id'] = rival_id
      user_name = members[rival_id]
      user_records[members[rival_id]] = record

    return jsonify(contest_info=contest_info, user_records=user_records, music_list=music_list, code='ok')
  except Exception, err:
    print sys.exc_info()[0], err
    return jsonify(code='error')

@app.route('/user/<rival_id>/history', defaults={'page':1})
@app.route('/user/<rival_id>/history/page/<int:page>')
@jsonp
def user_history(rival_id, page):
  try:
    r = getRedis()

    if not r.hexists('rival_id', rival_id):
      return jsonify(code='nodata')

    perpage = 20
    user_name = r.hget('rival_id', rival_id)
    idx = (page-1)*perpage
    cols = ['date', 'music', 'difficulty', 'score']
    history = [ dict(zip(cols, record.rsplit(':', 3))) for record in r.lrange('history:{0}'.format(rival_id), idx, idx+perpage-1) ]
    return jsonify(user_name=user_name, history=history, code='ok', perpage=perpage, total=r.llen('history:{0}'.format(rival_id)))
    
  except Exception, err:
    print sys.exc_info()[0], err
    return jsonify(code='error')

@app.route('/contest/<contest_id>/history', defaults={'page':1})
@app.route('/contest/<contest_id>/history/page/<int:page>')
@jsonp
def contest_history(contest_id, page):
  try:
    r = getRedis()

    perpage = 20
    contest_history_key = 'contest_history:{0}'.format(contest_id)
    if not r.exists(contest_history_key):
      return jsonify(code='nodata')
    idx = (page-1)*perpage
    cols = ['date', 'music', 'difficulty', 'score', 'rival_id']
    history = [ dict(zip(cols, record.rsplit(':', 4))) for record in r.lrange(contest_history_key, idx, idx+perpage-1) ]
    rival_ids = set()
    map(lambda _: rival_ids.add(_['rival_id']), history)
    rival_ids = dict(zip(rival_ids, r.hmget('rival_id', rival_ids)))
    for record in history:
      record['user_name'] = rival_ids[record['rival_id']]
    return jsonify(history=history, code='ok', perpage=perpage, total=r.llen(contest_history_key))

  except Exception, err:
    print sys.exc_info()[0], err
    return jsonify(code='error')

@app.route('/rss')
def rss():
  try:
    r = getRedis()
    cols = ['date', 'music', 'difficulty', 'score', 'name', 'pubdate']
    cols_new = ['date', 'music', 'difficulty', 'score', 'place', 'name', 'pubdate']
#    history = [ dict(zip(cols, record.rsplit('\t'))) for record in r.lrange('recent_history', 0, -1) ]
    history = []
    for record in r.lrange('recent_history', 0, -1):
      r = record.rsplit('\t')
      if len(r) == len(cols):
        r = dict(zip(cols, r))
        r['place'] = 'Unknown'
      elif len(r) == len(cols_new):
        r = dict(zip(cols_new, r))
      history.append(r)
    history.sort(lambda x, y: cmp(y['pubdate'], x['pubdate']) or cmp(x['date'], y['date']))
    history_item = [ {'title':'[{name}] {music} - {difficulty} - {score} - {date} - {place}'.format(**record), 'pubDate':strToUTC(record['pubdate'])} for record in history ]
    rss = PyRSS2Gen.RSS2(
      title = 'Jubeater',
      description = 'Jubeater',
      link = '',
      items = [ PyRSS2Gen.RSSItem(**item) for item in history_item ]
    )
    mimetype = 'application/xml'
    return current_app.response_class(rss.to_xml(encoding='utf-8'), mimetype=mimetype)

  except Exception, err:
    print sys.exc_info()[0], err
    return jsonify(code='error')

@app.route('/admin/music_list', methods=['GET', 'POST'])
@jsonp
def adminMusicList():
  if request.method == 'POST':
    try:
      info_data = base64.b64decode(request.json['data']).decode('utf-8')
      newInfo = {}
      for line in info_data.splitlines():
        s = line.split('\t')
        newInfo[s[0].encode('utf-8')] = json.dumps({
            'title': s[0],
            'artist': s[1],
            'bpm': s[2],
            'lv': [ int(_) for _ in s[3:6] ],
            'notes': [ int(_) for _ in s[6:9] ]
        })
      r = getRedis()
      r.hmset('music_info', newInfo)
      return jsonify(code='ok')
    except Exception, err:
      print sys.exc_info()[0], err
      return jsonify(code='error')
  else:
    try:
      r = getRedis()
      raw_data = r.hgetall('music_info')
      return jsonify(music_info=[ json.loads(_.decode('utf-8')) for _ in raw_data.itervalues() ])
    except Exception, err:
      print sys.exc_info()[0], err
      return jsonify(code='error')

@app.route('/admin/music_list/update', methods=['POST'])
@jsonp
def updateMusicInfo():
  try:
    key, info = request.json["key"], request.json["info"]
    r = getRedis()
    print r.hdel('music_info', key.encode('utf-8'))
    r.hset('music_info', info['title'].encode('utf-8'), json.dumps(info))
    return jsonify(code='ok')
  except Exception, err:
    print sys.exc_info()[0], err
    return jsonify(code='error')

@app.route('/admin/music_list/delete', methods=['POST'])
@jsonp
def deleteMusicInfo():
  try:
    info = request.json
    r = getRedis()
    res = r.hdel('music_info', info['title'].encode('utf-8'))
    return jsonify(code='ok', status=res)
  except Exception, err:
    print sys.exc_info()[0], err
    return jsonify(code='error')

if __name__ == '__main__':
  app.run(host='0.0.0.0', port=4416, debug=True)

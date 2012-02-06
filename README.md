## Jubeat Crawler by chisun

# package dependency
- httplib2
- redis
- BeautifulSoup
- gevent

# Initial auth_info Settings
- You have to set 'auth_info' to redis db
- redis> hset auth_info KID [konami id]
- redis> hset auth_info pass [konami pass]
- or call login([konami id], [konami pass])

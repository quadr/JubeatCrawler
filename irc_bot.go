package main

import (
	"crypto/tls"
	"fmt"
	redis "github.com/garyburd/redigo/redis"
	irc "github.com/quadr/goirc/client"
	"io/ioutil"
	"log"
	"math"
	"math/rand"
	"sort"
	"strconv"
	"strings"
	"time"
)

var msg = make(chan string, 256)

type MusicInfo struct {
	title, artist string
	bpm           string
	diffculty     string
	lv            int
	notes         int
}

func (m *MusicInfo) String() string {
	return fmt.Sprintf("Lv.%d - %s - %s - %s - Notes:%d - BPM:%s", m.lv, m.title, m.artist, m.diffculty, m.notes, m.bpm)
}

func atoi(s string) (i int) {
	i, _ = strconv.Atoi(s)
	return
}

var str_difficulty = []string{"BASIC", "ADVANCED", "EXTREME"}

func parseMusicInfo(raw string) (info []*MusicInfo) {
	s := strings.Split(raw, "\t")
	if len(s) == 1 {
		return
	}

	info = make([]*MusicInfo, 3)
	for i := 0; i < 3; i++ {
		info[i] = &MusicInfo{
			title:     s[0],
			artist:    s[1],
			diffculty: str_difficulty[i],
			bpm:       s[2],
			lv:        atoi(s[i+3]),
			notes:     atoi(s[i+6]),
		}
	}
	return
}

func adjustLevel(lv int) int {
	return int(math.Max(math.Min(float64(lv), 10), 1))
}

type MusicInfoContainer struct {
	allSongs []*MusicInfo
	lvSongs  map[int][]*MusicInfo
}

func makeMusicInfoContainer() *MusicInfoContainer {
	c := &MusicInfoContainer{
		lvSongs: make(map[int][]*MusicInfo),
	}

	content, err := ioutil.ReadFile("list.txt")
	if err != nil {
		log.Println("Init MusicInfo Failed")
	}
	lines := strings.Split(string(content), "\n")
	for _, line := range lines {
		infos := parseMusicInfo(line)
		c.allSongs = append(c.allSongs, infos...)
		for _, info := range infos {
			l := c.lvSongs[info.lv]
			c.lvSongs[info.lv] = append(l, info)
		}
	}
	return c
}

var musicinfos = makeMusicInfoContainer()

func readLog() {
	c, err := redis.Dial("tcp", ":6379")
	if err != nil {
		log.Println("Redis Connect Error : ", err)
		return
	}
	defer c.Close()
	c.Do("SELECT", 11)
	for {
		result, _ := redis.MultiBulk(c.Do("BRPOP", "IRC_HISTORY", 0))

		if result != nil {
			msg <- string(result[1].([]byte))
		}
	}
}

func addSachalUser(handle, rivalId string) error {
	c, err := redis.Dial("tcp", ":6379")
	if err != nil {
		log.Println("Redis Connect Error : ", err)
		return err
	}
	defer c.Close()
	c.Do("SELECT", 11)
	if _, err := c.Do("HSET", "rival_id", rivalId, handle); err != nil {
		return err
	}
	return nil
}

func selectMusic(conn *irc.Conn, lv ...int) {
	var info *MusicInfo
	var musiclist []*MusicInfo
	if len(lv) == 1 {
		switch {
		case lv[0] == 0:
			musiclist = musicinfos.allSongs
		case lv[0] > 0 && lv[0] < 11:
			musiclist = musicinfos.lvSongs[lv[0]]
		}
	} else if len(lv) == 2 {
		lv[0], lv[1] = adjustLevel(lv[0]), adjustLevel(lv[1])
		for i := lv[0]; i <= lv[1]; i++ {
			musiclist = append(musiclist, musicinfos.lvSongs[i]...)
		}
	}
	if len(musiclist) == 0 {
		conn.Privmsg("#jubeater", "잘못입력하셨습니다.")
		return
	}
	info = musiclist[rand.Int31n(int32(len(musiclist)))]
	conn.Privmsg("#jubeater", info.String())
}

func main() {
	rand.Seed(time.Now().UnixNano())
	c := irc.SimpleClient("Jubeat")
	c.SSL = true
	c.SSLConfig = &tls.Config{InsecureSkipVerify: true}

	go readLog()
	disconnected := make(chan bool)
	stopRead := make(chan bool)
	c.AddHandler("connected", func(conn *irc.Conn, line *irc.Line) {
		conn.Join("#jubeater")
	})

	c.AddHandler("JOIN", func(conn *irc.Conn, line *irc.Line) {
		if line.Nick == conn.Me.Nick {
			go func() {
				for {
					select {
					case m := <-msg:
						log.Println(m)
						conn.Privmsg("#jubeater", m)
					case <-stopRead:
						return
					}
				}
			}()
		}
	})

	c.AddHandler("PRIVMSG", func(conn *irc.Conn, line *irc.Line) {
		if len(line.Args) == 2 && line.Args[0][0] == '#' {
			cmds := strings.Fields(line.Args[1])
			if line.Nick == "s" {
				cmds = cmds[1:]
			}
			if len(cmds) > 0 && len(cmds[0]) > 2 && cmds[0][0] == '!' {
				switch cmds[0][1:] {
				case "선곡":
					var lv []int
					if len(cmds) > 1 {
						lvs := strings.Split(cmds[1], "-")
						for _, l := range lvs {
							lv = append(lv, atoi(l))
						}
					} else {
						lv = append(lv, 0)
					}
					sort.Ints(lv)
					selectMusic(conn, lv...)
				case "사찰":
					if len(cmds) == 3 {
						if err := addSachalUser(cmds[1], cmds[2]); err != nil {
							conn.Privmsg("#jubeater", err.Error())
						} else {
							conn.Privmsg("#jubeater", "사찰 등록 완료")
						}
					} else {
						conn.Privmsg("#jubeater", "!사찰 [Handle] [Rival ID]")
					}
				default:
					conn.Privmsg("#jubeater", "잘못된 명령입니다.")
				}
			}
		}
	})

	c.AddHandler("disconnected", func(conn *irc.Conn, line *irc.Line) {
		stopRead <- true
		disconnected <- true
	})

	for {
		if err := c.Connect("localhost:16661"); err != nil {
			log.Println("Connection error: ", err)
		} else {
			<-disconnected
		}
		time.Sleep(10 * time.Second)
	}
}

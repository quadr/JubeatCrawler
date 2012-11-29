package main

import (
	"crypto/tls"
	"fmt"
	irc "github.com/fluffle/goirc/client"
	redis "github.com/garyburd/redigo/redis"
	"io/ioutil"
	"log"
	"math/rand"
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

func selectMusic(lv int, conn *irc.Conn) {
	var info *MusicInfo
	switch {
	case lv == 0:
		info = musicinfos.allSongs[rand.Int31n(int32(len(musicinfos.allSongs)))]
	case lv > 0 && lv < 11:
		l := musicinfos.lvSongs[lv]
		info = l[rand.Int31n(int32(len(l)))]
	}
	if info == nil {
		conn.Privmsg("#jubeater", "잘못입력하셨습니다.")
		return
	}
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
					lv := 0
					if len(cmds) > 1 {
						lv = atoi(cmds[1])
					}
					selectMusic(lv, conn)
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
		}
		<-disconnected
		time.Sleep(10*time.Second)
	}
}

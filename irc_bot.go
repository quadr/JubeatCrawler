package main

import (
	irc "github.com/fluffle/goirc/client"
	redis "github.com/garyburd/redigo/redis"
//	"fmt"
	"log"
//	"strings"
	"crypto/tls"
)

var msg = make(chan string, 256)

func readLog() {
	c, err := redis.Dial("tcp", ":6379")
	if err != nil {
		log.Println("Redis Connect Error : ", err)
	}
	defer c.Close()
	c.Do("SELECT", 12)
	for {
		result, _ := redis.MultiBulk(c.Do("BRPOP", "IRC_HISTORY", 0))

		log.Println(result)
		if result != nil {
			msg <- string(result[1].([]byte))
		}
	}
}

func main() {
	c := irc.SimpleClient("Jubeat")
	c.SSL = true
	c.SSLConfig = &tls.Config{ InsecureSkipVerify: true }

	disconnected := make(chan bool)
	c.AddHandler("connected", func(conn *irc.Conn, line *irc.Line) {
		conn.Join("#jubeater")
	})

	c.AddHandler("JOIN", func(conn *irc.Conn, line *irc.Line) {
		if line.Nick == conn.Me.Nick {
			go readLog()
			go func() {
				for m := range msg {
					log.Println(m)
					conn.Privmsg("#jubeater", m)
				}
			} ()
		}
	})

	c.AddHandler("disconnected", func(conn *irc.Conn, line *irc.Line) { disconnected <- true })

	if err := c.Connect("localhost:16661"); err != nil {
		log.Println("Connection error: ", err)
		return
	}
	<- disconnected
}

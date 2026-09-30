package main

import (
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/19-84/farside/db"
	"github.com/19-84/farside/server"
	"github.com/19-84/farside/services"
)

func main() {
	err := db.InitializeDB()
	if err != nil {
		log.Fatal(err)
	}

	go func() {
		err = services.InitializeServices()
		if err != nil {
			log.Println("Error intializing services", err)
		}
	}()

	go db.InitCronTasks()

	signalChan := make(chan os.Signal, 1)
	signal.Notify(signalChan, os.Interrupt, syscall.SIGTERM)

	go func() {
		<-signalChan
		_ = db.CloseDB()
		os.Exit(0)
	}()

	server.RunServer()
}

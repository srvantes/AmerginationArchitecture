FROM ubuntu:latest
LABEL authors="srvnts"

ENTRYPOINT ["top", "-b"]
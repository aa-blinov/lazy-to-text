import socket, threading, time
srv=socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR,1); srv.bind(("127.0.0.1",18561)); srv.listen(512)
keep=[]
while True:
    c,_=srv.accept(); keep.append(c)

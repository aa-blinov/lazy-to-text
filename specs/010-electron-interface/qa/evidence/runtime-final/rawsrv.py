import socket, threading, time, sys
MODE=sys.argv[2]; port=int(sys.argv[1])
s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); s.bind(("127.0.0.1",port)); s.listen(50)
def h(c):
    try:
        c.settimeout(5)
        d=b""
        while b"\r\n\r\n" not in d: d+=c.recv(65536)
        if MODE=="garbage": c.sendall(b"GARBAGE\r\n\r\n")
        elif MODE=="chunk": c.sendall(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nContent-Type: application/json\r\n\r\nZZ\r\nxx")
        elif MODE=="drip":
            c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100000\r\n\r\n")
            for i in range(300): c.sendall(b" "); time.sleep(0.8)
        elif MODE=="silent": time.sleep(300)
        elif MODE=="drip_headers":
            for ch in b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello":
                c.sendall(bytes([ch])); time.sleep(0.8)
    except Exception: pass
    finally:
        try: c.close()
        except Exception: pass
while True:
    c,_=s.accept(); threading.Thread(target=h,args=(c,),daemon=True).start()

import socket, time

HOST="192.168.0.100"
PORT=5004

cmds = [b"\r", b"\r", b"\r", b"?\r", b"VERS\r", b"SERI\r", b"SMODE\r", b"SEND\r"]

with socket.create_connection((HOST, PORT), timeout=3) as s:
    s.settimeout(2)
    for c in cmds:
        print(">>", c)
        s.sendall(c)
        time.sleep(0.15)
        try:
            data = s.recv(4096)
        except socket.timeout:
            data = b""
        print("<<", data)
        if data:
            print(data.decode("ascii", errors="replace"))

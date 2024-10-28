import binascii
import datetime
import os
import queue
import socket
import sys
import time
from threading import Thread


sys.path.append(os.path.dirname(os.path.realpath(__file__)))
sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
from change_start_version_ip.bolai_protocol import bolai_protocol
from change_start_version_ip.mini_protocol import mini_protocol
from change_start_version_ip.xinwang_protocol import xinwang_protocol
from change_start_version_ip.api_protocol import api_protocol
from config import TCP_PORT
from tool.logger import MyLogger
from tool.wf_time_new import wf_time_new

prolog = MyLogger("main", level=20).logger

class change_server:

    def __init__(self):
        self.port = ('0.0.0.0', 37881)
        # 客服端集合
        self.tcpclients = set()
        self.timer = wf_time_new()
        #tcp链接
        self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
        # tcp keeplive
        self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self.tcp_socket.setsockopt(socket.SOL_TCP, socket.TCP_KEEPIDLE, 7200)
        self.tcp_socket.setsockopt(socket.SOL_TCP, socket.TCP_KEEPCNT, 2)
        self.tcp_socket.setsockopt(socket.SOL_TCP, socket.TCP_KEEPINTVL, 30)
        # 服务器端口
        self.tcp_socket.bind(self.port)
        self.tcp_socket.listen()
        # 队列
        self.q = queue.Queue(1024)


    def run(self):
        try:
            prolog.info('服务已启动...')
            while True:
                conn,addr = self.tcp_socket.accept()
                prolog.info("tcp连接上的客户端是,{}".format(addr))
                # 生产者
                product_msg_thread = Thread(target=self.product_msg, args=(conn, addr), daemon=True)
                product_msg_thread.start()
                # 消费者
                consumer_msg_thread = Thread(target=self.consumer_msg, daemon=True)
                consumer_msg_thread.start()
        except Exception as e:
            prolog.error(f"error:{e}")

    def product_msg(self,conn, addr):
        # 接收信息
        self.tcpclients.add((conn, addr, time.time()))
        front_data = ''
        while True:
            try:
                list_tcpclients = list(self.tcpclients)
                for clients in list_tcpclients[::-1]:
                    if clients[1] == addr:
                        list_tcpclients.remove(clients)

                    if clients[2] < time.time() - 300:
                        if clients in list_tcpclients:
                            list_tcpclients.remove(clients)
                            clients[0].close()

                self.tcpclients = set(list_tcpclients)
                self.tcpclients.add((conn, addr, time.time()))
                buf = conn.recv(1024)  # 1024 表示接收最大字节  防止内存溢出

                if len(buf) > 0:
                    data = ''
                    for letter in buf:
                        data += chr(letter)
                    if data.startswith('mini') or data.startswith('evapi'):
                        print(data)
                    else:
                        cbuf = binascii.b2a_hex(buf)
                        data = ''
                        for letter in cbuf:
                            data += chr(letter)
                    # 1. 如果开头 CCCC 新网，直接 队列
                    # 2. 如果fcff 开头，且结尾： fcee 入队列
                    # 3. 其他。拼接，并头尾提取 入队列
                    if data.startswith('cccc') or data.startswith('mini') or data.startswith('evapi'):
                        self.q.put([data, conn, addr])
                    elif data.startswith('fcfe') and data.endswith('fcee'):
                        self.q.put([data, conn, addr])
                    else:
                        front_data = front_data + data
                        if not front_data.startswith('fcfe'):
                            # 记录被丢弃的指令
                            prolog.error('addr:{} data:{}'.format(addr[0], front_data))
                            front_data = ''
                        if front_data.find('fcfe') >= 0 and front_data.find('fcee') >= 0:
                            new_data = front_data[front_data.find('fcfe'):front_data.find('fcee') + 4]
                            if new_data:
                                self.q.put([new_data, conn, addr])
                                front_data = front_data[front_data.find('fcee') + 4:]
                else:
                    list_tcpclient = list(self.tcpclients)
                    for client in list_tcpclient[::-1]:
                        if client[1] == addr:
                            list_tcpclient.remove(client)
                            self.tcpclients = set(list_tcpclient)
                    conn.close()
                    break
            except Exception as e:  # 因为异步的原因。可能设备离线后还在接收消息。
                prolog.error('请求异常...')
                conn.send('{"status":401,"msg":"请求异常."}'.encode('utf-8'))


    def consumer_msg(self):
        while True:
            if not self.q.empty():
                resp = self.q.get()
                data, conn, addr = resp[0], resp[1], resp[2]
                try:
                    if data.startswith('cccc'):
                        self.xinwang_protocol(data, conn, addr)
                    elif data.startswith('fcfe'):
                        if data.endswith('0e'):
                            data = data.replace('0e', '')
                        self.bolai_protocol(data, conn, addr)
                    elif data.startswith('mini'):
                        data_list = str(data).split('|')
                        self.mini_protocol(data_list[1:], conn, addr)
                    elif data.startswith('evapi'):
                        data_list = str(data).split('|')
                        self.api_protocol(data_list[1:], conn, addr)
                    else:
                        prolog.error(f'无效请求 addr:{addr},data:{data}')
                        conn.send('{"status":400,"msg":"无效请求"}'.encode('utf-8'))
                except Exception as e:
                    prolog.error(f'error:{str(e)}')
                    conn.send('{"status":400,"msg":"请求异常."}'.encode('utf-8'))


    def xinwang_protocol(self,data, conn, addr):
        xinwang_protocol(data, conn, addr)



    def bolai_protocol(self,data, conn, addr):
        print('bolai_protocol',data)
        bolai_protocol(data, conn, addr)



    def mini_protocol(self,data, conn, addr):
        mini_protocol(data, conn, addr, self.tcpclients)


    def api_protocol(self,data, conn, addr):
        api_protocol(data, conn, addr, self.tcpclients)









if __name__ == "__main__":
    # 创建服务器端的socket用于监听
    tcp_server = change_server()
    tcp_server.run()




import binascii
import datetime
import os
import queue
import socket
import sys
from threading import Thread


sys.path.append(os.path.dirname(os.path.realpath(__file__)))
sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
from change.bolai_protocol import bolai_protocol
from change.mini_protocol import mini_protocol
from change.xinwang_protocol import xinwang_protocol
from change.api_protocol import api_protocol
from config import TCP_PORT
from tool.logger import MyLogger
from tool.wf_time_new import wf_time_new

prolog = MyLogger("main", level=20).logger

class change_server:

    def __init__(self):
        self.port = ('0.0.0.0', 37881)
        # 客服端集合
        self.clients = set()
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
        # try:
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
        # except Exception as e:
        #     prolog.error(f"error:{e}")

    def product_msg(self,conn, addr):
        strat_recv_data = ''
        while True:
            #处理链接
            self.handle_client(conn,addr)
            #更新时间
            self.clients.add((conn,addr,self.timer.get_now()))
            #接收数据
            recv_data = conn.recv(1024)
            print('recv_data',recv_data)
            if recv_data:
                strat_recv_data = self.format_data(recv_data,strat_recv_data,conn, addr)
            else:
                # self.handle_client(conn,addr,is_close=True)
                prolog.error(f"conn:{conn},接收数据为空,断开链接")
                break


    def consumer_msg(self):
        while True:
            if not self.q.empty():
                resp = self.q.get()
                data, conn, addr = resp[0], resp[1], resp[2]
                # try:
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
                # except Exception as e:
                #     prolog.error(f'error:{str(e)}')
                #     conn.send('{"status":400,"msg":"请求异常."}'.encode('utf-8'))


    def xinwang_protocol(self,data, conn, addr):
        xinwang_protocol(data, conn, addr)



    def bolai_protocol(self,data, conn, addr):
        bolai_protocol(data, conn, addr)



    def mini_protocol(self,data, conn, addr):
        mini_protocol(data, conn, addr, self.clients)


    def api_protocol(self,data, conn, addr):
        api_protocol(data, conn, addr, self.clients)




    def handle_client(self, conn,addr,is_close=False):
        clients_ls = list(self.clients)
        # 判断连接是否存在和超时
        for client in clients_ls:
            # 移除不关闭(为了更新最近时间)
            if client[1] == addr:
                clients_ls.remove(client)
            #小于十分钟移除且关闭(说明链接已断开)
            if datetime.datetime.strptime(client[2], '%Y-%m-%d %H:%M:%S') < self.timer.get_now_bef_aft(minutes=10):
                clients_ls.remove(client)
                client[0].close()
        self.clients = set(clients_ls)
        if is_close:
            conn.close()

    def chr_data(self,recv_data):
        _recv_data = ''.join([chr(i) for i in recv_data])
        return _recv_data

    def format_data(self,recv_data,strat_recv_data,conn, addr):
        _recv_data = self.chr_data(recv_data)
        print('_recv_data',_recv_data)
        if _recv_data.startswith('mini') or _recv_data.startswith('evapi'):
            prolog.info(f'data:{_recv_data}')
        else:
            _recv_data = self.chr_data(binascii.b2a_hex(recv_data))
        if _recv_data.startswith('cccc') or _recv_data.startswith('mini') or _recv_data.startswith('evapi'):
            self.q.put([_recv_data, conn, addr])
        elif _recv_data.startswith('fcfe') and _recv_data.endswith('fcee'):
            self.q.put([_recv_data, conn, addr])
        else:
            strat_recv_data = strat_recv_data + _recv_data
            if not strat_recv_data.startswith('fcfe'):
                prolog.error(f"addr:{addr},strat_recv_data:{strat_recv_data}")
                strat_recv_data = ''
            if strat_recv_data.find('fcfe') >= 0 and strat_recv_data.find('fcee') >= 0:
                new_data = strat_recv_data[strat_recv_data.find('fcfe'):strat_recv_data.find('fcee') + 4]
                if new_data:
                    self.q.put([new_data, conn, addr])
                    strat_recv_data = strat_recv_data[strat_recv_data.find('fcee') + 4:]
        return strat_recv_data



if __name__ == "__main__":
    # 创建服务器端的socket用于监听
    tcp_server = change_server()
    tcp_server.run()




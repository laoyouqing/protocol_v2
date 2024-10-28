import binascii
import datetime
import json
import math
import os
import random
import sys
import time
from threading import Thread
from socket import *
import socket
sys.path.append(os.path.dirname(os.path.realpath(__file__)))
sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
from change.normal_query import get_access_token
from config import db_config, UDP_PORT, REQ_HOST
from model_door import Ev_pod_idno, User_white_list, User, Ev_recharge_package_order, Ev_note, Ev_setting, User_balance_log, Member_miniapp, \
    Ev_dealer_note, Ev_dealer_order, Member_payinfo, Ev_pod_door, Ev_pod_door_log
from tool.calc import low_high, dec2hex, high_low
from tool.logger import MyLogger
from tool.wf_mysql import wf_mysql_class
from tool.wf_time_new import wf_time_new
from tool.wx_sdk import tl_pay_sdk, wx_pay_sdk, wx_mini_sdk

prolog = MyLogger("main", level=20).logger
sob = wf_mysql_class(cursor_type=True)
timer = wf_time_new()


class UdpServer():

    udpclients = set()
    __ServerOpen = True

    def __init__(self, post=('0.0.0.0', 37882)):

        self.ServerPort = post
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 服务器端口
        self.udp_socket.bind(self.ServerPort)
        self.thread_rece = Thread(target=self.recv_msg)
        self.thread_send = Thread(target=self.send_msg)

    def start(self):
        prolog.info(self.getTime() + '37882:udp服务端已启动')
        self.thread_rece.start()
        self.thread_send.start()
        self.thread_rece.join()
        self.thread_send.join()

    def recv_msg(self):
        # 接收信息
        while True:
            try:
                buf, addr = self.udp_socket.recvfrom(1024)  # 1024 表示接收最大字节  防止内存溢出
                # 服务器记录客户端  记录连接IP信息
                prolog.info('udp连接上的客户端是{},{}'.format(self.getTime(), addr))

                if len(buf) > 0:
                    data = ''
                    for letter in buf:
                        data += chr(letter)
                    if data.startswith('mini') or data.startswith('evapi'):
                        prolog.info(data)
                    else:
                        cbuf = binascii.b2a_hex(buf)
                        prolog.info('len:{}'.format(len(cbuf)))
                        data = ''
                        for letter in cbuf:
                            data += chr(letter)
                    if data.startswith('17'):
                        # 处理门禁 WG Door协议
                        #判断该ip是否已在连接池中
                        if self.udpclients:
                            list_udpclient = list(self.udpclients)
                            for client in list_udpclient[::-1]:
                                if client[0] == addr or client[1] < time.time() - 70:
                                    list_udpclient.remove(client) #如果存在移除
                                    self.udpclients = set(list_udpclient)

                        # 把门禁ip放入IP池
                        self.udpclients.add((addr,time.time()))
                        self.wgdoor(data, addr)
                    elif data.startswith('mini'):
                        data_list = str(data).split('|')  # 切割命
                        self.udp_mini(data_list[1:], addr)
                    elif data.startswith('evapi'):
                        data_list = str(data).split('|')  # 切割命
                        self.udp_evapi(data_list[1:], addr)
                    else:
                        prolog.error(data)
            except Exception as e:  # 因为异步的原因。可能设备离线后还在接收消息。
                errorStr = 'code:2000:{}'.format(e)
                prolog.error(errorStr)

    def sent_to_all(self, data_info):
        # 系统广播信息
        for i in self.user_ip.keys():
            self.udp_socket.sendto(data_info.encode('utf-8'), i)

    def sent_to_all_cip(self, clientip, data):

        # 广播消息除了指定IP
        for ci in self.udpclients:
            if ci[0] == clientip:
                self.udp_socket.sendto(data.encode('utf-8'), ci)

    def getTime(self):
        return '[' + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + ']'

    def send_msg(self):
        while self.__ServerOpen:
            data_info = input()
            if data_info == 'exit':
                self.__ServerOpen = False
                self.sent_to_all(self.getTime() + ' 服务器系统已关闭，请自行下线')
                break

    def getimestamp(self):
        now_tm = (datetime.datetime.now().strftime('%Y%m%d%H%M%S'))
        time_array = time.strptime(now_tm, "%Y%m%d%H%M%S")
        stamp_tm = int(time.mktime(time_array))
        data = hex(stamp_tm)[2:].zfill(8)
        return data


    # 门禁通信协议处理
    def wgdoor(self, data, addr):
        if len(data) == 128:
            # 数据内容解析
            cmd = data[2:4]
            idevsn = int(low_high(data[8:16]), 16)  # 设备序列号
            idevsnhex = data[8:16]  # 设备序列号
            prolog.info('idevsnhex:{}'.format(str(idevsnhex)))
            ev_pod_door = Ev_pod_door.findAll('serialnum=?',[str(idevsn)])
            for door in ev_pod_door:
                door.lastip = str(addr)
                door.update()

            if cmd == '20':
                # 实时监控用
                '''
                    8-11	记录的索引号
                    (=0表示没有记录)	4	0x00000000
                '''
                recordindex = data[16:24]
                '''
                    12	记录类型**********************************************
                    0=无记录
                    1=刷卡记录
                    2=门磁,按钮, 设备启动, 远程开门记录
                    3=报警记录	1
                    0xFF=表示指定索引位的记录已被覆盖掉了.  请使用索引0, 取回最早一条记录的索引值
                '''
                recordtype = data[24:26]  # 刷卡记录

                '''
                    13	有效性(0 表示不通过, 1表示通过)
                '''
                recordvaild = data[26:28]
                '''
                    14	门号 (1,2,3,4)
                '''
                recorddoorno = data[28:30]
                '''
                    15	进门/出门(1表示进门, 2表示出门)	1	0x01
                '''
                recordinorout = data[30:32]

                '''
                    16-19	卡号(类型是刷卡记录时)
                '''
                recordcardnohex = data[32:40]


                recordcardno = str(int(low_high(recordcardnohex), 16)).zfill(10)

                '''
                    20-26	刷卡时间:
                    年月日时分秒 (采用BCD码)
                '''
                recordtime = data[40:54]
                '''
                    27	记录原因代码(可以查 “刷卡记录说明.xls”文件的ReasonNO)
                '''
                reason = data[54:56]
                '''
                    0=无记录
                    1=刷卡记录
                    2=门磁,按钮, 设备启动, 远程开门记录
                    3=报警记录	1
                    0xFF=表示指定索引位的记录已被覆盖掉了.  请使用索引0, 取回最早一条记录的索引值
                '''

                if recordtype == '00':
                    prolog.debug('无刷卡记录')
                elif recordtype == '01':
                    prolog.info('recordinorout:{}'.format(recordinorout))
                    prolog.info('recordcardno:{}'.format(recordcardno))
                    prolog.info('recordtype is :{}'.format(recordtype))
                    ev_pod_doors = Ev_pod_door.findAll('serialnum=?', [idevsn])
                    if ev_pod_doors:
                        ev_pod_door = ev_pod_doors[0]
                        # 门禁刷卡
                        ev_pod_idno = Ev_pod_idno.findAll('idno=? and note_id=?',[recordcardno,ev_pod_door.note_id])
                        if not ev_pod_idno:
                            # rfid刷卡
                            ev_pod_idno = Ev_pod_idno.findAll('rfid=? and note_id=?',[recordcardno, ev_pod_door.note_id])

                        if ev_pod_idno:
                            ev_pod_idno = ev_pod_idno[0]
                            is_open = True  # 默认允许开门
                            note_id = ev_pod_door.note_id
                            mini_id = ev_pod_idno.mini_id
                            user_id = ev_pod_idno.user_id
                            user = User.find(user_id)
                            if ev_pod_door.readhead_num == 1:  #单读头
                                #是否白名单跟套餐包
                                user_white_list,ev_recharge_package_orders = white_package_func(mini_id, user, ev_pod_door)
                                if user_white_list or ev_recharge_package_orders:
                                    if is_open:
                                        ev_pod_door_log = Ev_pod_door_log(
                                            mini_id=mini_id, note_id=note_id, user_id=user_id, serialnum=idevsn,
                                            idno=recordcardno, doorindex=recorddoorno, doorio=recordinorout,
                                            status=1,
                                            reason=reason, pay_status=3, type=1,add_time=timer.get_now())
                                        ev_pod_door_log.save()

                                        # 刷卡记录  回复 控制开门状态
                                        # 回复指令
                                        repheard = '17'
                                        repcmd = '40' + '0'.zfill(4)
                                        repdata = '0'.zfill(128)

                                        redata = repheard + repcmd + idevsnhex + recorddoorno + repdata
                                        redata = redata[0:128]
                                        repsend = binascii.a2b_hex(redata)
                                        prolog.info('回复1740指令')
                                        self.udp_socket.sendto(repsend, addr)
                                        return
                                else:
                                    '''不是白名单'''
                                    #单双读头进出门
                                    is_open = readhead_door_calc(is_open, ev_pod_door, user, mini_id, note_id, user_id,
                                                       idevsn, recordcardno, recorddoorno, recordinorout, reason,ev_pod_door.readhead_num)
                            else: #双读头
                                # 单双读头进出门
                                is_open = readhead_door_calc(is_open, ev_pod_door, user, mini_id, note_id, user_id,
                                                             idevsn, recordcardno, recorddoorno, recordinorout,
                                                             reason,ev_pod_door.readhead_num)
                            prolog.info('is_open:{}'.format(is_open))

                            if is_open:
                                # 刷卡记录  回复 控制开门状态
                                # 回复指令
                                repheard = '17'
                                repcmd = '40' + '0'.zfill(4)
                                repdata = '0'.zfill(128)

                                redata = repheard + repcmd + idevsnhex + recorddoorno + repdata
                                redata = redata[0:128]
                                # redata = redata.zfill(128)

                                repsend = binascii.a2b_hex(redata)
                                prolog.info('回复1740指令')
                                self.udp_socket.sendto(repsend, addr)

                else:
                    # 类型异常
                    prolog.debug('其他')

        else:
            # 字符串长度校验 失败
            prolog.error(data)


    # 小程序通信
    def udp_mini(self, data, addr):
        # try:
        data = json.loads(data[0])
        counter = 0  # 记录发送到客户端的个数
        if data['command'] == 'code_door':
            mini_id = data['mini_id']
            serialnum = data['serialnum']
            ev_pod_door = Ev_pod_door.findAll('mini_id=? and serialnum=?', [mini_id, serialnum])
            if ev_pod_door:
                data['ip'] = ev_pod_door[0].lastip
        for ci in self.udpclients:
            prolog.info(self.udpclients)
            if str(ci[0]) == data['ip']: #是这个门禁的ip
                if data['token'] == 'qfevserver':
                    if data['command'] == 'code_door':
                        print('扫码----')
                        # 门禁扫码进出
                        mini_id = data['mini_id']
                        user_id = data['user_id']
                        if user_id==6471:
                            print(1111111111111)
                        serialnum = data['serialnum']
                        doorindex = data['doorindex']
                        doorio = data['doorio']  # 1进门 2出门
                        #门禁设备
                        ev_pod_doors = Ev_pod_door.findAll('mini_id=? and serialnum=?', [mini_id, serialnum])
                        if ev_pod_doors:
                            ev_pod_door = ev_pod_doors[0]
                            ev_note = Ev_note.find(ev_pod_door.note_id)
                            # 白名单用户
                            user = User.find(user_id)
                            if user_id == 6471:
                                print(2222222222222222,user)
                            if user:
                                if ev_pod_door.status == 1:
                                    # 在线
                                    if ev_pod_door.readhead_num == 1:
                                        #单读头
                                        #是否白名单跟套餐包
                                        user_white_list,ev_recharge_package_orders = white_package_func(mini_id, user, ev_pod_door)
                                        print('ev_recharge_package_orders',ev_recharge_package_orders)
                                        if user_white_list or ev_recharge_package_orders:
                                            if user_white_list:
                                                pay_type = 1
                                            else:
                                                pay_type = 2
                                            order_id = f"{timer.get_now('%Y%m%d%H%M%S')}{user_id}"
                                            ev_pod_door_log_out = Ev_pod_door_log(id=order_id, mini_id=mini_id,
                                                                                  note_id=ev_pod_door.note_id,
                                                                                  user_id=user_id, serialnum=serialnum, type=0,
                                                                                  doorindex=ev_pod_door.doorindex, is_invalid=0,
                                                                                  is_settled=0,pay_type=pay_type,
                                                                                  doorio=doorio, status=1, pay_status=2,
                                                                                  is_due=0,add_time=timer.get_now())
                                            ev_pod_door_log_out.save()
                                            repheard = '17'
                                            repcmd = '40' + '0'.zfill(4)
                                            repdata = '0'.zfill(128)
                                            idevsnhex = dec2hex(
                                                ev_pod_door.serialnum).zfill(8)
                                            idevsnhex = high_low(idevsnhex)
                                            prolog.info('idevsnhex:{}'.format(idevsnhex))

                                            redata = repheard + repcmd + idevsnhex + doorindex + repdata
                                            repmsg = redata[0:128]
                                            prolog.info('出门 resp data:{}'.format(repmsg))
                                            repsend = binascii.a2b_hex(repmsg)
                                            self.udp_socket.sendto(repsend, ci[0])
                                            self.udp_socket.sendto('{"status":200,"msg":"开门成功"}'.encode('utf-8'), addr)
                                            return
                                        else:
                                            if user_id == 6471:
                                                print(3333333333333, user)
                                            #不是白名单和没有套餐包
                                            ev_pod_door_logs = Ev_pod_door_log.findAll(
                                                'mini_id=? and note_id=? and user_id=? and serialnum=? and type=0 and status=1',
                                                [mini_id, ev_pod_door.note_id, user_id, serialnum], orderBy='add_time desc')   #最后一次扫码开门

                                            if ev_pod_door_logs:
                                                if ev_pod_door_logs[0].doorio == doorio:
                                                    self.udp_socket.sendto('{"status":400,"msg":"开门失败，不能连续进门或出门操作"}'.encode('utf-8'), addr)
                                                    return
                                            if ev_note.is_temporary_site == 0:  #非临时停场地
                                                if user_id == 6471:
                                                    print(44444444444444, user)
                                                if doorio == '02':   #出门
                                                    #扫码读头是否能进出门判断
                                                    resp = scan_readhead_door(ev_pod_door_logs, mini_id, user_id, ev_note,ev_pod_door)
                                                    if resp['status'] != 200:
                                                        self.udp_socket.sendto(str(resp).encode('utf-8'),addr)
                                                        return
                                                    ############出门收费#############
                                                    doorin_time = timer.time2timestamp(ev_pod_door_logs[0].add_time.strftime("%Y-%m-%d %H:%M:%S"))   # 进门时间
                                                    doorout_time = time.time()  # 出门时间
                                                    order_id = f"{timer.get_now('%Y%m%d%H%M%S')}{user_id}"
                                                    ev_pod_door_log_out = Ev_pod_door_log(
                                                        id=order_id,mini_id=mini_id,note_id=ev_pod_door.note_id,
                                                        user_id=user_id,serialnum=serialnum,type=0,
                                                        doorindex=ev_pod_door.doorindex,is_invalid=0,
                                                        is_settled=0,doorio=doorio,status=0,pay_status=1,is_due=0,add_time=timer.get_now())
                                                    ev_pod_door_log_out.save()
                                                    if doorout_time - doorin_time > ev_note.free_time * 60:
                                                        resp = scan_doorout_fee_func(mini_id, user_id, ev_pod_door,doorin_time, doorout_time, ev_note,
                                                                                     ev_pod_door_log_out, user,ev_pod_door.readhead_num)
                                                        if resp['status'] != 201:
                                                            self.udp_socket.sendto(str(resp).encode('utf-8'), addr)
                                                            return
                                                    else:
                                                        ev_pod_door_log_out.pay_status = 1 #免费
                                                        ev_pod_door_log_out.update()
                                                    # 出门
                                                    repheard = '17'
                                                    repcmd = '40' + '0'.zfill(4)
                                                    repdata = '0'.zfill(128)
                                                    idevsnhex = dec2hex(ev_pod_door.serialnum).zfill(8)
                                                    idevsnhex = high_low(idevsnhex)
                                                    prolog.info('idevsnhex:{}'.format(idevsnhex))
                                                    redata = repheard + repcmd + idevsnhex + doorindex + repdata
                                                    repmsg = redata[0:128]
                                                    prolog.info('出门 resp data:{}'.format(repmsg))
                                                    repsend = binascii.a2b_hex(repmsg)
                                                    self.udp_socket.sendto(repsend, ci[0])
                                                    ev_pod_door_log_out.status = 1
                                                    ev_pod_door_log_out.update()
                                                    self.udp_socket.sendto('{"status":200,"msg":"出门成功"}'.encode('utf-8'), addr)
                                                    return
                                                # 进门
                                                repheard = '17'
                                                repcmd = '40' + '0'.zfill(4)
                                                repdata = '0'.zfill(128)
                                                idevsnhex = dec2hex(ev_pod_door.serialnum).zfill(8)
                                                idevsnhex = high_low(idevsnhex)
                                                prolog.info('idevsnhex:{}'.format(idevsnhex))
                                                redata = repheard + repcmd + idevsnhex + doorindex + repdata
                                                repmsg = redata[0:128]
                                                prolog.info('进门 resp data:{}'.format(repmsg))
                                                repsend = binascii.a2b_hex(repmsg)
                                                self.udp_socket.sendto(repsend, ci[0])
                                                ev_pod_door_log = Ev_pod_door_log(
                                                    mini_id=mini_id,note_id=ev_pod_door.note_id,
                                                    user_id=user_id,serialnum=serialnum,
                                                    type=0,doorindex=ev_pod_door.doorindex,
                                                    doorio=doorio,status=1,pay_status=1,add_time=timer.get_now())
                                                ev_pod_door_log.save()
                                                self.udp_socket.sendto('{"status":200,"msg":"进门成功"}'.encode('utf-8'), addr)
                                                print('进门成功。。。')
                                            else:  #临停场地先付费
                                                if user_id == 6471:
                                                    print(555555555555555555555, user)
                                                if ev_pod_door_logs:
                                                    order_id = f"{timer.get_now('%Y%m%d%H%M%S')}{user_id}"
                                                    ev_pod_door_log_out = Ev_pod_door_log(
                                                        id=order_id, mini_id=mini_id, note_id=ev_pod_door.note_id,
                                                        user_id=user_id, serialnum=serialnum, type=0,
                                                        doorindex=ev_pod_door.doorindex,
                                                        is_invalid=0, is_settled=0, doorio=doorio, status=0,
                                                        pay_status=1, is_due=0,add_time=timer.get_now())
                                                    ev_pod_door_log_out.save()
                                                    if doorio == '01': #进门
                                                        #临停进门
                                                        resp = temporary_site_door(ev_note, user_id, ev_pod_door_log_out, mini_id,ev_pod_door, order_id)
                                                        if resp['status'] == 201:
                                                            # 进门
                                                            repheard = '17'
                                                            repcmd = '40' + '0'.zfill(4)
                                                            repdata = '0'.zfill(128)
                                                            idevsnhex = dec2hex(ev_pod_door.serialnum).zfill(8)
                                                            idevsnhex = high_low(idevsnhex)
                                                            prolog.info('idevsnhex:{}'.format(idevsnhex))
                                                            redata = repheard + repcmd + idevsnhex + doorindex + repdata
                                                            repmsg = redata[0:128]
                                                            prolog.info('进门 resp data:{}'.format(repmsg))
                                                            repsend = binascii.a2b_hex(repmsg)
                                                            self.udp_socket.sendto(repsend, ci[0])
                                                            self.udp_socket.sendto('{"status":200,"msg":"进门成功"}'.encode('utf-8'), addr)
                                                            ev_pod_door_log_out.status = 1
                                                            ev_pod_door_log_out.update()
                                                            return
                                                        else:
                                                            self.udp_socket.sendto(str(resp).encode('utf-8'),addr)
                                                            return
                                                    else: #出门
                                                        #出门如果在免费停放时长内需退款
                                                        door_refund(ev_pod_door_logs, user, ev_note)
                                                        repheard = '17'
                                                        repcmd = '40' + '0'.zfill(4)
                                                        repdata = '0'.zfill(128)
                                                        idevsnhex = dec2hex(ev_pod_door.serialnum).zfill(8)
                                                        idevsnhex = high_low(idevsnhex)
                                                        prolog.info('idevsnhex:{}'.format(idevsnhex))
                                                        redata = repheard + repcmd + idevsnhex + doorindex + repdata
                                                        repmsg = redata[0:128]
                                                        prolog.info('出门 resp data:{}'.format(repmsg))
                                                        repsend = binascii.a2b_hex(repmsg)
                                                        self.udp_socket.sendto(repsend, ci[0])
                                                        ev_pod_door_log_out.status = 1
                                                        ev_pod_door_log_out.update()
                                                        self.udp_socket.sendto('{"status":200,"msg":"出门成功"}'.encode('utf-8'), addr)
                                                        return
                                                else:
                                                    # 还没有开门记录
                                                    if doorio == '02': #出门
                                                        self.udp_socket.sendto('{"status":400,"msg":"出门失败，不是通过扫码进的门"}'.encode('utf-8'),addr)
                                                        return
                                                    else: #首次进门
                                                        order_id = f"{timer.get_now('%Y%m%d%H%M%S')}{user_id}"
                                                        ev_pod_door_log = Ev_pod_door_log(id=order_id,
                                                            mini_id=mini_id,note_id=ev_pod_door.note_id,
                                                            user_id=user_id,serialnum=serialnum,
                                                            type=0,doorindex=ev_pod_door.doorindex,
                                                            doorio=doorio,status=1,pay_status=1,add_time=timer.get_now())
                                                        ev_pod_door_log.save()
                                                        # 临停进门
                                                        resp = temporary_site_door(ev_note, user_id,ev_pod_door_log, mini_id,ev_pod_door, order_id)
                                                        if resp['status'] == 201:
                                                            # 进门
                                                            repheard = '17'
                                                            repcmd = '40' + '0'.zfill(4)
                                                            repdata = '0'.zfill(128)
                                                            idevsnhex = dec2hex(ev_pod_door.serialnum).zfill(8)
                                                            idevsnhex = high_low(idevsnhex)
                                                            prolog.info('idevsnhex:{}'.format(idevsnhex))
                                                            redata = repheard + repcmd + idevsnhex + doorindex + repdata
                                                            repmsg = redata[0:128]
                                                            prolog.info('进门 resp data:{}'.format(repmsg))
                                                            repsend = binascii.a2b_hex(repmsg)
                                                            self.udp_socket.sendto(repsend, ci[0])
                                                            self.udp_socket.sendto('{"status":200,"msg":"进门成功"}'.encode('utf-8'), addr)
                                                            return
                                                        else:
                                                            ev_pod_door_log.status = 0
                                                            ev_pod_door_log.update()
                                                            self.udp_socket.sendto(str(resp).encode('utf-8'), addr)
                                                            return
                                    else: #双读头
                                        ev_pod_door_logs = Ev_pod_door_log.findAll('mini_id=? and note_id=? and user_id=? and type=0 and status=1',
                                            [mini_id, ev_pod_door.note_id, user_id],orderBy='add_time desc')  # 最后一次扫码开门

                                        if ev_pod_door_logs:
                                            if ev_pod_door_logs[0].doorio == doorio:
                                                self.udp_socket.sendto('{"status":400,"msg":"开门失败，不能连续进门或出门操作"}'.encode('utf-8'), addr)
                                                return
                                        if ev_note.is_temporary_site == 0: #非临停场地
                                            if doorio == '02':
                                                #扫码读头是否能进出门判断
                                                resp = scan_readhead_door(ev_pod_door_logs, mini_id, user_id, ev_note,ev_pod_door)
                                                if resp['status'] != 200:
                                                    self.udp_socket.sendto(str(resp).encode('utf-8'), addr)
                                                    return
                                                ############出门收费#############
                                                order_id = f"{timer.get_now('%Y%m%d%H%M%S')}{user_id}"
                                                ev_pod_door_log_out = Ev_pod_door_log(
                                                    id=order_id,mini_id=mini_id,note_id=ev_pod_door.note_id,
                                                    user_id=user_id,serialnum=serialnum,type=0,doorindex=ev_pod_door.doorindex,
                                                    is_invalid=0,is_settled=0,doorio=doorio,status=0,
                                                    pay_status=1,is_due=0,add_time=timer.get_now())
                                                ev_pod_door_log_out.save()

                                                doorin_time = timer.time2timestamp(ev_pod_door_logs[0].add_time.strftime("%Y-%m-%d %H:%M:%S"))  # 进门时间
                                                doorout_time = time.time()  # 出门时间
                                                if doorout_time - doorin_time > ev_note.free_time * 60: #是否超过免费停放时长
                                                    user_white_list = User_white_list.findAll(
                                                        'mini_id=? and user_id=? and note_id=? and special_end>? and special_start<?',
                                                        [mini_id, user_id, ev_pod_door.note_id, timer.get_now(), timer.get_now()])
                                                    if not user_white_list: #不是白名单
                                                        resp = scan_doorout_fee_func(mini_id, user_id, ev_pod_door,
                                                                              doorin_time, doorout_time, ev_note,
                                                                              ev_pod_door_log_out, user, ev_pod_door.readhead_num)
                                                        if resp['status'] != 201:
                                                            self.udp_socket.sendto(str(resp).encode('utf-8'),addr)
                                                            return
                                                    else:
                                                        ev_pod_door_log_out.pay_type = 1   #白名单
                                                        ev_pod_door_log_out.pay_status = 2
                                                        ev_pod_door_log_out.update()
                                                else:
                                                    ev_pod_door_log_out.pay_type = 1   #免费
                                                    ev_pod_door_log_out.pay_status = 2
                                                    ev_pod_door_log_out.update()

                                                repheard = '17'
                                                repcmd = '40' + '0'.zfill(4)
                                                repdata = '0'.zfill(128)
                                                idevsnhex = dec2hex(ev_pod_door.serialnum).zfill(8)
                                                idevsnhex = high_low(idevsnhex)
                                                prolog.info('idevsnhex:{}'.format(idevsnhex))
                                                redata = repheard + repcmd + idevsnhex + doorindex + repdata
                                                repmsg = redata[0:128]
                                                prolog.info('出门 resp data:{}'.format(repmsg))
                                                repsend = binascii.a2b_hex(repmsg)
                                                self.udp_socket.sendto(repsend, ci[0])
                                                ev_pod_door_log_out.status = 1
                                                ev_pod_door_log_out.update()
                                                self.udp_socket.sendto('{"status":200,"msg":"出门成功"}'.encode('utf-8'), addr)
                                                return
                                            # 进门
                                            repheard = '17'
                                            repcmd = '40' + '0'.zfill(4)
                                            repdata = '0'.zfill(128)
                                            idevsnhex = dec2hex(ev_pod_door.serialnum).zfill(8)
                                            idevsnhex = high_low(idevsnhex)
                                            prolog.info('idevsnhex:{}'.format(idevsnhex))
                                            redata = repheard + repcmd + idevsnhex + doorindex + repdata
                                            repmsg = redata[0:128]
                                            prolog.info('进门 resp data:{}'.format(repmsg))
                                            repsend = binascii.a2b_hex(repmsg)
                                            self.udp_socket.sendto(repsend, ci[0])
                                            order_id = f"{timer.get_now('%Y%m%d%H%M%S')}{user_id}"
                                            ev_pod_door_log = Ev_pod_door_log(
                                                id=order_id,
                                                mini_id=mini_id,note_id=ev_pod_door.note_id,user_id=user_id,
                                                serialnum=serialnum,type=0,doorindex=ev_pod_door.doorindex,
                                                doorio=doorio,status=1,pay_status=1,add_time=timer.get_now())
                                            ev_pod_door_log.save()
                                            self.udp_socket.sendto('{"status":200,"msg":"进门成功"}'.encode('utf-8'), addr)
                                        else: #临停场地先付费
                                            if ev_pod_door_logs:
                                                order_id = f"{timer.get_now('%Y%m%d%H%M%S')}{user_id}"
                                                ev_pod_door_log_out = Ev_pod_door_log(
                                                    id=order_id, mini_id=mini_id, note_id=ev_pod_door.note_id,
                                                    user_id=user_id, serialnum=serialnum, type=0,
                                                    doorindex=ev_pod_door.doorindex,
                                                    is_invalid=0, is_settled=0, doorio=doorio, status=0,
                                                    pay_status=1, is_due=0,add_time=timer.get_now())
                                                ev_pod_door_log_out.save()
                                                if doorio == '01': #进门
                                                    user_white_list = User_white_list.findAll(
                                                        'mini_id=? and user_id=? and note_id=? and special_end>? and special_start<?',
                                                        [mini_id, user_id, ev_pod_door.note_id, timer.get_now(),timer.get_now()])
                                                    ev_recharge_package_orders = Ev_recharge_package_order.findAll(
                                                        'mini_id=? and user_id=? and note_id=? and pay_status=20 and end_time>=? and order_status=20',
                                                        [mini_id, user_id, ev_pod_door.note_id, timer.get_now()],orderBy='end_time desc')  # 没有过期的套餐包
                                                    if user_white_list or ev_recharge_package_orders:  # 白名单和套餐包
                                                        # 进门
                                                        repheard = '17'
                                                        repcmd = '40' + '0'.zfill(4)
                                                        repdata = '0'.zfill(128)
                                                        idevsnhex = dec2hex(ev_pod_door.serialnum).zfill(8)
                                                        idevsnhex = high_low(idevsnhex)
                                                        prolog.info('idevsnhex:{}'.format(idevsnhex))
                                                        redata = repheard + repcmd + idevsnhex + doorindex + repdata
                                                        repmsg = redata[0:128]
                                                        prolog.info('进门 resp data:{}'.format(repmsg))
                                                        repsend = binascii.a2b_hex(repmsg)
                                                        self.udp_socket.sendto(repsend, ci[0])
                                                        self.udp_socket.sendto('{"status":200,"msg":"进门成功"}'.encode('utf-8'), addr)
                                                        ev_pod_door_log_out.status = 1
                                                        ev_pod_door_log_out.pay_type = 1
                                                        ev_pod_door_log_out.pay_status = 2
                                                        ev_pod_door_log_out.update()
                                                        return
                                                    else:
                                                        # 临停进门
                                                        resp = temporary_site_door(ev_note, user_id, ev_pod_door_log_out,mini_id, ev_pod_door, order_id)
                                                        if resp['status'] == 201:
                                                            # 进门
                                                            repheard = '17'
                                                            repcmd = '40' + '0'.zfill(4)
                                                            repdata = '0'.zfill(128)
                                                            idevsnhex = dec2hex(ev_pod_door.serialnum).zfill(8)
                                                            idevsnhex = high_low(idevsnhex)
                                                            prolog.info('idevsnhex:{}'.format(idevsnhex))
                                                            redata = repheard + repcmd + idevsnhex + doorindex + repdata
                                                            repmsg = redata[0:128]
                                                            prolog.info('进门 resp data:{}'.format(repmsg))
                                                            repsend = binascii.a2b_hex(repmsg)
                                                            print(repmsg)
                                                            self.udp_socket.sendto(repsend, ci[0])
                                                            self.udp_socket.sendto('{"status":200,"msg":"进门成功"}'.encode('utf-8'), addr)
                                                            ev_pod_door_log_out.status = 1
                                                            ev_pod_door_log_out.update()
                                                            return
                                                        else:
                                                            self.udp_socket.sendto(str(resp).encode('utf-8'), addr)
                                                            return
                                                else: #出门
                                                    # 出门如果在免费停放时长内需退款
                                                    door_refund(ev_pod_door_logs, user, ev_note)
                                                    ev_pod_door_log_due = Ev_pod_door_log.findAll('mini_id=? and user_id=? and note_id=? and is_due=1 and type=0',[mini_id, user_id, ev_note.id])
                                                    if ev_pod_door_log_due:  # 判断是否有欠费
                                                        pod_door_log = ev_pod_door_log_due[0]
                                                        self.udp_socket.sendto(
                                                            str({"status": 204, "msg": "套餐已过期","time": str(pod_door_log.due_time),
                                                                 "log_id": pod_door_log.id,"note_name": ev_note.note_name,
                                                                 "address": ev_note.address, "note_id": ev_note.id,
                                                                 'lastip': ev_pod_door.lastip}).encode('utf-8'), addr)
                                                        return
                                                    doorin_time = ev_pod_door_logs[0].add_time.strftime("%Y-%m-%d %H:%M:%S")
                                                    ev_recharge_package_orders = Ev_recharge_package_order.findAll(
                                                        'mini_id=? and user_id=? and note_id=? and pay_status=20 and start_time<=? and end_time>=? and order_status=20',
                                                        [mini_id, user_id, ev_pod_door.note_id, timer.time2timestamp(doorin_time),timer.time2timestamp(doorin_time)],orderBy='end_time desc')  # 没有过期的套餐包
                                                    if ev_recharge_package_orders:
                                                        if timer.time2timestamp(ev_recharge_package_orders[0].end_time.strftime("%Y-%m-%d %H:%M:%S")) < time.time(): #套餐包到期时间小于当前时间 套餐到期欠费
                                                            money_time = math.ceil((time.time() - timer.time2timestamp(ev_recharge_package_orders[0].end_time.strftime("%Y-%m-%d %H:%M:%S"))) / (24 * 60 * 60))
                                                            money = ev_note.money * money_time  # 套餐包外超时计费费用
                                                            ev_pod_door_log_out.is_due = 1
                                                            ev_pod_door_log_out.due_time = ev_recharge_package_orders[0].end_time  # 欠费时间=套餐包到期时间
                                                            ev_pod_door_log_out.money = money
                                                            ev_pod_door_log_out.update()
                                                            self.udp_socket.sendto(
                                                                str({"status": 204, "msg": "套餐已过期", "money": money,
                                                                     "time": str(ev_recharge_package_orders[0].end_time),
                                                                     "log_id": ev_pod_door_log_out.id,
                                                                     "note_name": ev_note.note_name,
                                                                     "address": ev_note.address, "note_id": ev_note.id,
                                                                     'lastip': ev_pod_door.lastip}).encode('utf-8'),addr)
                                                            return
                                                    #出门
                                                    repheard = '17'
                                                    repcmd = '40' + '0'.zfill(4)
                                                    repdata = '0'.zfill(128)
                                                    idevsnhex = dec2hex(ev_pod_door.serialnum).zfill(8)
                                                    idevsnhex = high_low(idevsnhex)
                                                    prolog.info('idevsnhex:{}'.format(idevsnhex))
                                                    redata = repheard + repcmd + idevsnhex + doorindex + repdata
                                                    repmsg = redata[0:128]
                                                    prolog.info('进门 resp data:{}'.format(repmsg))
                                                    repsend = binascii.a2b_hex(repmsg)
                                                    self.udp_socket.sendto(repsend, ci[0])
                                                    self.udp_socket.sendto('{"status":200,"msg":"出门成功"}'.encode('utf-8'), addr)
                                                    ev_pod_door_log_out.status = 1
                                                    ev_pod_door_log_out.update()
                                                    return
                                            else: # 还没有开门记录
                                                if doorio == '02':  # 出门
                                                    self.udp_socket.sendto('{"status":400,"msg":"出门失败，不是通过扫码进的门"}'.encode('utf-8'), addr)
                                                    return
                                                else:  # 首次进门
                                                    order_id = f"{timer.get_now('%Y%m%d%H%M%S')}{user_id}"
                                                    ev_pod_door_log = Ev_pod_door_log(id=order_id,mini_id=mini_id,
                                                                                      note_id=ev_pod_door.note_id,user_id=user_id,
                                                                                      serialnum=serialnum,type=0,
                                                                                      doorindex=ev_pod_door.doorindex,
                                                                                      doorio=doorio,status=1, pay_status=1,
                                                                                      add_time=timer.get_now())
                                                    ev_pod_door_log.save()
                                                    user_white_list = User_white_list.findAll(
                                                        'mini_id=? and user_id=? and note_id=? and special_end>? and special_start<?',
                                                        [mini_id, user_id, ev_pod_door.note_id, timer.get_now(),timer.get_now()])
                                                    ev_recharge_package_orders = Ev_recharge_package_order.findAll(
                                                        'mini_id=? and user_id=? and note_id=? and pay_status=20 and end_time>=? and order_status=20',
                                                        [mini_id, user_id, ev_pod_door.note_id, timer.get_now()],orderBy='end_time desc')  # 没有过期的套餐包
                                                    if user_white_list or ev_recharge_package_orders:  # 白名单和套餐包
                                                        # 进门
                                                        repheard = '17'
                                                        repcmd = '40' + '0'.zfill(4)
                                                        repdata = '0'.zfill(128)
                                                        idevsnhex = dec2hex(ev_pod_door.serialnum).zfill(8)
                                                        idevsnhex = high_low(idevsnhex)
                                                        prolog.info('idevsnhex:{}'.format(idevsnhex))
                                                        redata = repheard + repcmd + idevsnhex + doorindex + repdata
                                                        repmsg = redata[0:128]
                                                        prolog.info('进门 resp data:{}'.format(repmsg))
                                                        repsend = binascii.a2b_hex(repmsg)
                                                        self.udp_socket.sendto(repsend, ci[0])
                                                        self.udp_socket.sendto('{"status":200,"msg":"进门成功"}'.encode('utf-8'), addr)
                                                        return
                                                    else:
                                                        # 临停进门
                                                        resp = temporary_site_door(ev_note, user_id, ev_pod_door_log,mini_id, ev_pod_door, order_id)
                                                        if resp['status'] == 201:
                                                            # 进门
                                                            repheard = '17'
                                                            repcmd = '40' + '0'.zfill(4)
                                                            repdata = '0'.zfill(128)
                                                            idevsnhex = dec2hex(ev_pod_door.serialnum).zfill(8)
                                                            idevsnhex = high_low(idevsnhex)
                                                            prolog.info('idevsnhex:{}'.format(idevsnhex))
                                                            redata = repheard + repcmd + idevsnhex + doorindex + repdata
                                                            repmsg = redata[0:128]
                                                            prolog.info('进门 resp data:{}'.format(repmsg))
                                                            repsend = binascii.a2b_hex(repmsg)
                                                            self.udp_socket.sendto(repsend, ci[0])
                                                            self.udp_socket.sendto('{"status":200,"msg":"进门成功"}'.encode('utf-8'), addr)
                                                            return
                                                        else:
                                                            ev_pod_door_log.status = 0
                                                            ev_pod_door_log.update()
                                                            self.udp_socket.sendto(str(resp).encode('utf-8'), addr)
                                                            return
                                else:
                                    self.udp_socket.sendto(
                                        '{"status":400,"msg":"门禁是离线状态"}'.encode('utf-8'), addr)
                            else:
                                self.udp_socket.sendto(
                                    '{"status":400,"msg":"用户未授权"}'.encode('utf-8'), addr)
                        else:
                            self.udp_socket.sendto(
                                '{"status":400,"msg":"设备序列号不存在"}'.encode('utf-8'), addr)

                    elif data['command'] == 'due_pay':
                        # 门禁欠费付款
                        mini_id = data['mini_id']
                        user_id = data['user_id']
                        log_id = data['log_id']
                        ev_pod_door_log = Ev_pod_door_log.find(log_id)
                        user = User.find(user_id)
                        money = ev_pod_door_log.money
                        balance = user.balance
                        ev_note = Ev_note.find(ev_pod_door_log.note_id)
                        # 获取分成比例
                        first_proportion, second_proportion = dealer_proportion(ev_note, mini_id)

                        first_proportion_money = money * (first_proportion / 100)  # 一级（代理商）分成
                        second_proportion_money = money * (second_proportion / 100)  # 二级（物业）分成
                        ev_pod_door_log.first_proportion_money = first_proportion_money
                        ev_pod_door_log.second_proportion_money = second_proportion_money
                        ev_pod_door_log.update()
                        if balance > money:
                            user.balance -= money
                            user.update()
                            ev_pod_door_log.pay_status = 4
                            ev_pod_door_log.money = money
                            ev_pod_door_log.is_due = 0
                            ev_pod_door_log.status = 1
                            ev_pod_door_log.pay_time = timer.get_now()
                            ev_pod_door_log.update()
                            sob_handle = sob.sql_open(db_config)
                            value_info = {
                                'mini_id': mini_id,
                                'note_id': ev_pod_door_log.note_id,
                                'user_id': user_id,
                                'scene': 21,
                                'type': 2,
                                'money': money,
                                'describes': '用户消费(钱包扣款)',
                                'add_time': timer.get_now()
                            }
                            sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_user_balance_log',
                                                                       [value_info])
                            sob.sql_close(sob_handle)

                            # 开门
                            repheard = '17'
                            repcmd = '40' + '0'.zfill(4)
                            repdata = '0'.zfill(128)

                            idevsnhex = dec2hex(
                                ev_pod_door_log.serialnum).zfill(8)
                            idevsnhex = high_low(idevsnhex)

                            redata = repheard + repcmd + idevsnhex + \
                                str(ev_pod_door_log.doorindex).zfill(2) + repdata

                            repmsg = redata[0:128]
                            prolog.info('出门 resp data:{}'.format(repmsg))
                            repsend = binascii.a2b_hex(repmsg)
                            self.udp_socket.sendto(repsend, ci[0])
                            #分成收入计算
                            proportion_money(ev_pod_door_log, mini_id, ev_note)
                            self.udp_socket.sendto(
                                str({'msg': '支付成功', 'status': 200}).encode('utf-8'), addr)
                        else:
                            total_money = int(money * 100)
                            member_miniapp = Member_miniapp.find(mini_id)
                            member_payinfo = Member_payinfo.findAll('mini_id=?', [mini_id])[0]
                            try:
                                if member_payinfo.pay_type == 1:
                                    notify_url = f'{REQ_HOST}/api/wx_door_scancode_payback/{member_payinfo.orgid}'
                                    results, data = wx_pay_sdk().mini_pay(member_miniapp.authorizer_appid,
                                                                          member_payinfo.mchid,
                                                                          log_id, total_money, user.open_id,
                                                                          notify_url, member_payinfo.apikey,member_payinfo.key_pem)
                                    if results['xml']['return_code'] == 'SUCCESS':
                                        if results['xml']['result_code'] == 'SUCCESS':
                                            self.udp_socket.sendto(
                                                str({'data': data, 'status': 200}).encode('utf-8'), addr)
                                            return
                                        else:
                                            return_msg = results['xml']['return_msg']
                                    else:
                                        return_msg = results['xml']['return_msg']
                                    self.udp_socket.sendto(
                                        str({'return_msg': return_msg, 'status': 400}).encode('utf-8'), addr)

                                else:
                                    notify_url = f'{REQ_HOST}/api/tl_door_scancode_payback'
                                    tl_pay = tl_pay_sdk()
                                    resp = tl_pay.tl_mini_pay(member_payinfo.apikey, member_payinfo.orgid,
                                                              member_payinfo.mchid,
                                                              log_id,
                                                              total_money, notify_url,
                                                              member_payinfo.key_pem)
                                    self.udp_socket.sendto(
                                        str({'data': resp, 'status': 200}).encode('utf-8'), addr)
                                    return
                            except BaseException:
                                self.udp_socket.sendto(
                                    str({'msg': '支付异常', 'status': 400}).encode('utf-8'), addr)
                    counter += 1
                else:
                    self.udp_socket.sendto(
                        '{"status":400,"msg":"token验证失败."}'.encode('utf-8'), addr)
        if counter == 0:
            self.udp_socket.sendto(
                '{"status": 400, "msg": "无效ip."}'.encode('utf-8'), addr)
            return


    def udp_evapi(self, data, addr):
        data = json.loads(data[0])
        try:
            for ci in self.udpclients:
                if str(ci[0]) == data['ip']:
                    try:
                        if data['token'] == 'qfevserver':
                            if data['command'] == 'payback_door':
                                print('门禁回调')
                                # 门禁回调
                                serialnum = data['serialnum']
                                doorindex = data['doorindex']

                                repheard = '17'
                                repcmd = '40' + '0'.zfill(4)
                                repdata = '0'.zfill(128)

                                idevsnhex = dec2hex(serialnum).zfill(8)
                                idevsnhex = high_low(idevsnhex)
                                prolog.info('idevsnhex:{}'.format(idevsnhex))

                                redata = repheard + repcmd + idevsnhex + doorindex.zfill(2) + repdata
                                repmsg = redata[0:128]
                                prolog.info('开门 resp data:{}'.format(repmsg))
                                repsend = binascii.a2b_hex(repmsg)
                                self.udp_socket.sendto(repsend, ci[0])
                                self.udp_socket.sendto('{"status": 200, "msg": "开门成功"}'.encode('utf-8'), addr)
                                return
                        else:
                            self.udp_socket.sendto('{"status": 400, "msg": "token验证失败."}'.encode('utf-8'), addr)
                            return
                    except Exception as e:
                        errorStr = 'code:2001:{}'.format(e)
                        prolog.error(errorStr)
                        self.udp_socket.sendto('{"status": 400, "msg": "请求异常."}'.encode('utf-8'), addr)
                        return
            self.udp_socket.sendto('{"status": 400, "msg": "无效ip."}'.encode('utf-8'), addr)
            return
        except Exception as e:
            errorStr = 'code:2002:{}'.format(e)
            prolog.error(errorStr)
            self.udp_socket.sendto('{"status": 400, "msg": "请求异常."}'.encode('utf-8'), addr)





def proportion_money(ev_pod_door_log_out,mini_id,ev_note):
    sob_handle = sob.sql_open(db_config)
    try:
        # 分成收入计算
        if ev_pod_door_log_out.second_proportion_money:
            ev_dealer_notes = Ev_dealer_note.findAll(
                'mini_id=? and find_in_set(?,note_id) and type=6',
                [mini_id, ev_note.id])
            if ev_dealer_notes:
                ev_dealer_note = ev_dealer_notes[0]
                ev_dealer_note.freeze_money += ev_pod_door_log_out.second_proportion_money
                ev_dealer_note.update()
                ev_account_manage = User.findAll(
                    'mini_id=? find_in_set(?,note_id) and type=6',
                    [mini_id, ev_note.id])[0]
                value_info = {
                    'mini_id': mini_id,
                    'note_id': ev_note.id,
                    'user_id': ev_account_manage.id,
                    'order_id': ev_pod_door_log_out.id,
                    'order_price': ev_pod_door_log_out.money,
                    'share_money': ev_pod_door_log_out.second_proportion_money,
                    'type': 6,
                    'add_time': timer.get_now(),
                    'update_time': timer.get_now()
                }
                sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_dealer_order', [value_info])
        if ev_pod_door_log_out.first_proportion_money:
            ev_dealer_notes_agents = Ev_dealer_note.findAll(
                'mini_id=? and find_in_set(?,note_id) and type=5',
                [mini_id, ev_note.id])
            if ev_dealer_notes_agents:
                ev_dealer_note_agent = ev_dealer_notes_agents[0]
                ev_dealer_note_agent.freeze_money += ev_pod_door_log_out.first_proportion_money
                ev_dealer_note_agent.update()
                ev_agent = User.findAll('mini_id=? and find_in_set(?,note_id) and type=5',
                    [mini_id, ev_note.id])[0]
                value_info = {
                    'mini_id': mini_id,
                    'note_id': ev_note.id,
                    'user_id': ev_agent.id,
                    'order_id': ev_pod_door_log_out.id,
                    'order_price': ev_pod_door_log_out.money,
                    'share_money': ev_pod_door_log_out.first_proportion_money,
                    'type': 5,
                    'add_time': timer.get_now(),
                    'update_time': timer.get_now()
                }
                sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_dealer_order', [value_info])
    except BaseException:
        prolog.error('code:2003:门禁分成收入异常')
    sob.sql_close(sob_handle)



def due_submsg(ev_note,ev_recharge_package_orders,money,user):
    '''欠费消息通知'''
    try:
        ev_settings = Ev_setting.findAll('mini_id=? and title=?', [ev_note.mini_id, 'submsg'])
        values_json = ev_settings[0].values_json  # 基础设置
        values_json = json.loads(values_json)
        template_id = values_json['order']['pay']['template_id']
        access_token = get_access_token(ev_note.mini_id)
        wx_deve = wx_mini_sdk()
        # 套餐包到期时间
        due_time = ev_recharge_package_orders[0].end_time.strftime("%Y-%m-%d %H:%M:%S")
        days = (time.time() - timer.time2timestamp(due_time)) / (24 * 3600)
        data = {
            "thing1": {
                "value": ev_note.note_name
            },
            "thing2": {
                "value": str(int(days)) + '天'
            },
            "amount4": {
                "value": str(money) + '元'
            },
            "thing5": {
                "value": '门禁欠费，可点击进入小程序支付'
            }
        }
        wx_deve.send_tempalte_keyword(access_token, user.open_id, template_id,
                                      'pages/user/children/monthly-charge', data)
    except:
        prolog.error('code:2004:订阅消息发送失败')




def temporary_site_door(ev_note,user_id,ev_pod_door_log,mini_id,ev_pod_door,order_id):
    '''临停进门'''
    money = ev_note.money  # 门禁费用单次
    #获取分成比例
    first_proportion,second_proportion = dealer_proportion(ev_note, mini_id)
    user = User.find(user_id)
    balance = user.balance
    first_proportion_money = money * (first_proportion / 100)  # 一级（代理商）分成
    second_proportion_money = money * (second_proportion / 100)  # 二级（物业）分成
    ev_pod_door_log.first_proportion_money = first_proportion_money
    ev_pod_door_log.second_proportion_money = second_proportion_money
    if balance > money:
        user.balance -= money
        user.update()
        ev_pod_door_log.pay_type = 3
        ev_pod_door_log.pay_time = timer.get_now()
        ev_pod_door_log.pay_status = 2
        ev_pod_door_log.money = money
        ev_pod_door_log.update()
        sob_handle = sob.sql_open(db_config)
        value_info = {
            'mini_id': mini_id,
            'note_id': ev_pod_door.note_id,
            'user_id': user_id,
            'scene': 21,
            'type': 2,
            'start_time': timer.get_now(),
            'money': money,
            'describes': '用户消费(钱包扣款)',
            'add_time': timer.get_now()
        }
        sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_user_balance_log', [value_info])
        sob.sql_close(sob_handle)
        # 分成
        proportion_money(ev_pod_door_log, mini_id, ev_note)
        return {'msg': '支付成功', 'status': 201}
    else:
        total_money = int(money * 100)
        member_miniapp = Member_miniapp.find(mini_id)
        member_payinfo = Member_payinfo.findAll('mini_id=?', [mini_id])[0]
        try:
            if member_payinfo.pay_type == 1:
                notify_url = f'{REQ_HOST}/api/wx_door_scancode_payback/{member_payinfo.orgid}'
                results, data = wx_pay_sdk().mini_pay(
                    member_miniapp.authorizer_appid,
                    member_payinfo.mchid, order_id,
                    total_money, user.open_id, notify_url, member_payinfo.apikey,member_payinfo.key_pem)
            else:
                notify_url = f'{REQ_HOST}/api/tl_door_scancode_payback'
                tl_pay = tl_pay_sdk()
                resp = tl_pay.tl_mini_pay(member_payinfo.apikey, member_payinfo.orgid,
                                          member_payinfo.mchid,
                                          order_id,
                                          total_money, notify_url,
                                          member_payinfo.key_pem)
                return {'data': resp, 'status': 200}
            if results['xml']['return_code'] == 'SUCCESS':
                if results['xml']['result_code'] == 'SUCCESS':
                    ev_pod_door_log.money = money
                    ev_pod_door_log.pay_type = 4
                    ev_pod_door_log.update()
                    return {'data': data, 'status': 200}
                else:
                    return_msg = results['xml']['return_msg']
            else:
                return_msg = results['xml']['return_msg']
            return {'return_msg': return_msg, 'status': 400}
        except BaseException:
            return {'msg': '支付异常', 'status': 400}




def white_package_func(mini_id,user,ev_pod_door):
    '''是否白名单跟套餐包'''
    # 白名单用户
    user_white_list = User_white_list.findAll(
        'mini_id=? and user_id=? and note_id=? and special_end>? and special_start<?',
        [mini_id, user.id, ev_pod_door.note_id, timer.get_now(), timer.get_now()])
    print("user_white_list",user_white_list)
    # 查看是否有包月套餐

    ev_recharge_package_orders = Ev_recharge_package_order.findAll(
        'mini_id=? and user_id=? and note_id=? and pay_status=20 and order_status=20 and end_time>=? and start_time<=?', [mini_id, user.id,ev_pod_door.note_id,timer.get_now(),timer.get_now()])
    return user_white_list,ev_recharge_package_orders




def one_readhead_door(ev_pod_door_log,recordcardno):
    '''读头是否能进出门判断'''
    if ev_pod_door_log:
        if ev_pod_door_log.doorio != '01':
            # 不是进门
            is_open = False
        else:
            if recordcardno == ev_pod_door_log.idno:
                is_open = True  # 进出门卡号相同
            else:
                is_open = False
    else:
        # 不是刷卡orRFID
        is_open = False
    return is_open



def scan_readhead_door(ev_pod_door_logs,mini_id, user_id, ev_note,ev_pod_door):
    '''扫码读头是否能进出门判断'''
    if ev_pod_door_logs:
        # 如果是出门，判断进门是否是扫码进门
        if ev_pod_door_logs[0].doorio != '01':
            # 不是进门
            return {"status":400,"msg":"出门失败，不是通过扫码进的门"}
    else:
        return {"status":400,"msg":"出门失败，不是通过扫码进的门"}

    ev_pod_door_log_due = Ev_pod_door_log.findAll('mini_id=? and user_id=? and note_id=? and is_due=1 and type=0',
                                                  [mini_id, user_id, ev_note.id])
    if ev_pod_door_log_due:  # 判断是否有欠费
        pod_door_log = ev_pod_door_log_due[0]
        return {"status": 204, "msg": "套餐已过期",
                 "time": pod_door_log.due_time,
                 "log_id": pod_door_log.id, "note_name": ev_note.note_name,
                 "address": ev_note.address, "note_id": ev_note.id,
                 'lastip': ev_pod_door.lastip}
    return {'status':200,'msg':'成功'}


def dealer_proportion(ev_note,mini_id):
    '''获取分成比例'''
    if ev_note.is_ind_dealer == 1:  # 开启单独分成
        first_proportion = ev_note.first_proportion
        second_proportion = ev_note.second_proportion
    else:
        ev_dealer_setting = Ev_setting.findAll('mini_id=? and title="settlement"', [mini_id])
        if ev_dealer_setting:
            values_json = ev_dealer_setting[0].values_json  # 基础设置
            values_json = json.loads(values_json)
            first_proportion = int(values_json.get('first_proportion',0))  # 一级分成比例
            second_proportion = int(values_json.get('second_proportion',0))  # 二级分成比例
        else:
            first_proportion = 0
            second_proportion = 0
    return first_proportion,second_proportion




def doorout_fee_func(is_open,mini_id,user,ev_pod_door,doorin_time,ev_note,doorout_time,ev_pod_door_log,note_id,user_id,readhead_num):
    '''出门收费计算'''
    ev_recharge_package_orders = Ev_recharge_package_order.findAll(
        'mini_id=? and user_id=? and note_id=? and pay_status=20 and start_time<=? and end_time>=? and order_status=20',
        [mini_id, user_id, ev_pod_door.note_id, timer.timestamp2time(doorin_time), timer.timestamp2time(doorin_time)], orderBy='end_time desc')
    if not ev_recharge_package_orders:
        # 获取分成比例
        first_proportion, second_proportion = dealer_proportion(ev_note, mini_id)
        lead_time = math.ceil((doorout_time - doorin_time) / (24 * 60 * 60))
        money = ev_note.money * lead_time  # 超时计费费用
        first_proportion_money = money * (first_proportion / 100)  # 一级（代理商）分成
        second_proportion_money = money * (second_proportion / 100)  # 二级（物业）分成
        ev_pod_door_log.first_proportion_money = first_proportion_money
        ev_pod_door_log.second_proportion_money = second_proportion_money
        if user.balance > money:
            user.balance -= money
            user.update()
            ev_pod_door_log.pay_status = 4
            ev_pod_door_log.money = money
            ev_pod_door_log.pay_time = timer.get_now()
            ev_pod_door_log.update()

            sob_handle = sob.sql_open(db_config)
            value_info = {
                'mini_id': mini_id,
                'note_id': note_id,
                'user_id': user_id,
                'scene': 21,
                'type': 2,
                'start_time': timer.timestamp2time(doorin_time),
                'end_time': timer.timestamp2time(doorout_time),
                'money': money,
                'describes': '用户消费(钱包扣款)',
                'add_time': timer.get_now()
            }
            sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_user_balance_log', [value_info])
            sob.sql_close(sob_handle)
            # 分成
            proportion_money(ev_pod_door_log, mini_id, ev_note)
        else:
            is_open = False  # 卡没钱
            ev_pod_door_log.is_due = 1
            ev_pod_door_log.money = money
            ev_pod_door_log.update()
    else:
        if readhead_num == 1:
            money_time = math.ceil((doorout_time - timer.time2timestamp(ev_recharge_package_orders[0].end_time.strftime("%Y-%m-%d %H:%M:%S"))) / (24 * 60 * 60))
            money = ev_note.money * money_time  # 套餐包外超时计费费用
            is_open = False  # 卡没钱
            ev_pod_door_log.is_due = 1
            ev_pod_door_log.money = money
            ev_pod_door_log.due_time = ev_recharge_package_orders[0].end_time
            ev_pod_door_log.update()
            # 欠费消息通知
            due_submsg(ev_note, ev_recharge_package_orders, money, user)
        else:
            if timer.time2timestamp(ev_recharge_package_orders[0].end_time.strftime("%Y-%m-%d %H:%M:%S")) < doorout_time:
                money_time = math.ceil((doorout_time - timer.time2timestamp(ev_recharge_package_orders[0].end_time.strftime("%Y-%m-%d %H:%M:%S"))) / (24 * 60 * 60))
                money = ev_note.money * money_time  # 套餐包外超时计费费用
                ev_pod_door_log.is_due = 1
                ev_pod_door_log.due_time = ev_recharge_package_orders[0].end_time
                ev_pod_door_log.money = money
                ev_pod_door_log.update()
                is_open = False
                # 欠费消息通知
                due_submsg(ev_note, ev_recharge_package_orders, money, user)
            else:
                ev_pod_door_log.pay_status = 3
                ev_pod_door_log.update()
    return is_open




def scan_doorout_fee_func(mini_id, user_id, ev_pod_door, doorin_time,doorout_time,ev_note,ev_pod_door_log_out,user,readhead_num):
    '''扫码出门收费计算'''
    ev_recharge_package_orders = Ev_recharge_package_order.findAll(
        'mini_id=? and user_id=? and note_id=? and pay_status=20 and start_time<=? and end_time>=? and order_status=20',
        [mini_id, user_id, ev_pod_door.note_id, timer.timestamp2time(doorin_time), timer.timestamp2time(doorin_time)], orderBy='end_time desc')
    # 不是通过套餐包进的门，扣费
    if not ev_recharge_package_orders:
        # 获取分成比例
        first_proportion, second_proportion = dealer_proportion(ev_note, mini_id)
        lead_time = math.ceil((doorout_time - doorin_time) / (24 * 60 * 60))  # 天数
        money = ev_note.money * lead_time  # 超时计费费用
        first_proportion_money = money * (first_proportion / 100)  # 一级（代理商）分成
        second_proportion_money = money * (second_proportion / 100)  # 二级（物业）分成
        ev_pod_door_log_out.first_proportion_money = first_proportion_money
        ev_pod_door_log_out.second_proportion_money = second_proportion_money
        if user.balance > money:
            user.balance -= money
            user.update()
            ev_pod_door_log_out.pay_type = 3
            ev_pod_door_log_out.pay_status = 2
            ev_pod_door_log_out.money = money
            ev_pod_door_log_out.pay_time = timer.get_now()
            ev_pod_door_log_out.update()

            sob_handle = sob.sql_open(db_config)
            value_info = {
                'mini_id': mini_id,
                'note_id': ev_pod_door.note_id,
                'user_id': user_id,
                'scene': 21,
                'type': 2,
                'start_time': timer.timestamp2time(doorin_time),
                'end_time': timer.timestamp2time(doorout_time),
                'money': money,
                'describes': '用户消费(钱包扣款)',
                'add_time': timer.get_now()
            }
            sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_user_balance_log', [value_info])
            sob.sql_close(sob_handle)
            # 分成
            proportion_money(ev_pod_door_log_out, mini_id, ev_note)
        else:
            # 发起微信支付
            resp = door_wx_pay(money, mini_id, ev_pod_door_log_out.id, user, ev_pod_door_log_out)
            # self.udp_socket.sendto(str(resp).encode('utf-8'), addr)
            return resp
    else:  # 套餐包进的门，套餐已过期
        if readhead_num == 1:#单读头
            money_time = math.ceil((doorout_time - timer.time2timestamp(ev_recharge_package_orders[0].end_time.strftime("%Y-%m-%d %H:%M:%S"))) / (24 * 60 * 60))
            money = ev_note.money * money_time  # 套餐包外超时计费费用
            ev_pod_door_log_out.is_due = 1
            ev_pod_door_log_out.due_time = ev_recharge_package_orders[0].end_time  # 欠费时间=套餐包到期时间
            ev_pod_door_log_out.money = money
            ev_pod_door_log_out.update()
            return {"status": 204, "msg": "套餐已过期", "money": money,
                     "time": str(ev_recharge_package_orders[0].end_time),
                     "log_id": ev_pod_door_log_out.id, "note_name": ev_note.note_name,
                     "address": ev_note.address, "note_id": ev_note.id,
                     'lastip': ev_pod_door.lastip}
        else:
            if timer.time2timestamp(ev_recharge_package_orders[0].end_time.strftime("%Y-%m-%d %H:%M:%S")) < doorout_time:
                money_time = math.ceil((doorout_time - timer.time2timestamp(ev_recharge_package_orders[0].end_time.strftime("%Y-%m-%d %H:%M:%S"))) / (24 * 60 * 60))
                money = ev_note.money * money_time  # 套餐包外超时计费费用
                ev_pod_door_log_out.is_due = 1
                ev_pod_door_log_out.due_time = ev_recharge_package_orders[0].end_time
                ev_pod_door_log_out.money = money
                ev_pod_door_log_out.update()
                return {"status": 204, "msg": "套餐已过期", "money": money,
                        "time": str(ev_recharge_package_orders[0].end_time),
                        "log_id": ev_pod_door_log_out.id, "note_name": ev_note.note_name,
                        "address": ev_note.address, "note_id": ev_note.id,
                        'lastip': ev_pod_door.lastip}
            else:
                ev_pod_door_log_out.pay_type = 2
                ev_pod_door_log_out.pay_status = 2
                ev_pod_door_log_out.update()
    return {'status':201,'msg':'成功'}



def create_door_log(is_open,mini_id,note_id,user_id,idevsn,recordcardno,recorddoorno,recordinorout,reason):
    '''进门成功创建进门记录'''
    if is_open:  # 进门
        ev_pod_door_log = Ev_pod_door_log(
            mini_id=mini_id, note_id=note_id, user_id=user_id, serialnum=idevsn,
            idno=recordcardno, doorindex=recorddoorno, doorio=recordinorout,
            status=1, reason=reason, pay_status=1, type=1,add_time=timer.get_now())
        ev_pod_door_log.save()




def readhead_door_calc(is_open,ev_pod_door, user,mini_id, note_id, user_id, idevsn, recordcardno, recorddoorno, recordinorout, reason,readhead_num):
    '''单双读头进出门'''
    ev_pod_door_logs = Ev_pod_door_log.findAll(
        'mini_id=? and note_id=? and user_id=? and type=1 and status=1',
        [mini_id, note_id, user.id], orderBy='add_time desc')
    if ev_pod_door_logs:
        ev_pod_door_log = ev_pod_door_logs[0]
        if ev_pod_door_log.doorio == recordinorout:  # 重复进出门
            is_open = False
        if recordinorout == '02' and is_open:  # 出门
            # 读头是否能进出门判断
            is_open = one_readhead_door(ev_pod_door_log, recordcardno)
            due_pod_door_log = Ev_pod_door_log.findAll('mini_id=? and user_id=? and note_id=? and is_due=1',
                                                       [mini_id, user.id, note_id])
            if due_pod_door_log:  # 是否有欠费
                is_open = False
            else:
                ############出门收费#############
                ev_note = Ev_note.find(note_id)
                order_id = f"{timer.get_now('%Y%m%d%H%M%S')}{user_id}"
                ev_pod_door_log = Ev_pod_door_log(
                    id=order_id, mini_id=mini_id,
                    note_id=note_id, user_id=user_id,
                    serialnum=idevsn, idno=recordcardno,
                    doorindex=recorddoorno, doorio=recordinorout,
                    status=0, reason=reason,
                    pay_status=1, type=1, is_due=0,add_time=timer.get_now())
                ev_pod_door_log.save()
            if is_open:
                doorin_time = timer.time2timestamp(ev_pod_door_logs[0].add_time.strftime("%Y-%m-%d %H:%M:%S"))  # 进门时间
                doorout_time = time.time()  # 出门时间
                if doorout_time - doorin_time > ev_note.free_time * 60:  # 是否超过免费停放时长
                    if readhead_num == 1: #单读头
                        # 出门收费计算
                        is_open = doorout_fee_func(is_open, mini_id, user, ev_pod_door,
                                                   doorin_time, ev_note, doorout_time,
                                                   ev_pod_door_log, note_id, user_id,
                                                   ev_pod_door.readhead_num)
                    else: #双读头
                        user_white_list = User_white_list.findAll(
                            'mini_id=? and user_id=? and note_id=? and special_end>? and special_start<?',
                            [mini_id, user_id, ev_pod_door.note_id, timer.get_now(),
                             timer.get_now()])
                        if not user_white_list:  # 不是白名单
                            # 出门收费计算
                            is_open = doorout_fee_func(is_open, mini_id, user, ev_pod_door,
                                                       doorin_time, ev_note, doorout_time,
                                                       ev_pod_door_log, note_id, user_id,
                                                       ev_pod_door.readhead_num)
                        else:
                            ev_pod_door_log.pay_status = 2
                            ev_pod_door_log.update()
                else:
                    ev_pod_door_log.pay_status = 2
                    ev_pod_door_log.update()
            if is_open:
                ev_pod_door_log.status = 1
                ev_pod_door_log.update()
        else:  # 进门
            # 进门成功创建进门记录
            create_door_log(is_open, mini_id, note_id, user_id, idevsn, recordcardno, recorddoorno, recordinorout,
                            reason)
    else:
        # 进门成功创建进门记录
        create_door_log(is_open, mini_id, note_id, user_id, idevsn, recordcardno, recorddoorno, recordinorout, reason)
    return is_open




def door_wx_pay(money,mini_id,order_id,user,ev_pod_door_log_out):
    '''发起微信支付'''
    total_money = int(money * 100)
    member_miniapp = Member_miniapp.find(mini_id)
    member_payinfo = Member_payinfo.findAll('mini_id=?', [mini_id])[0]
    try:
        if member_payinfo.pay_type == 1:
            notify_url = f'{REQ_HOST}/api/wx_door_scancode_payback/{member_payinfo.orgid}'
            results, data = wx_pay_sdk().mini_pay(
                member_miniapp.authorizer_appid,
                member_payinfo.mchid, order_id,
                total_money, user.open_id, notify_url,member_payinfo.apikey,member_payinfo.key_pem)
        else:
            notify_url = f'{REQ_HOST}/api/tl_door_scancode_payback'
            tl_pay = tl_pay_sdk()
            resp = tl_pay.tl_mini_pay(member_payinfo.apikey, member_payinfo.orgid,
                                      member_payinfo.mchid,
                                      order_id,
                                      total_money, notify_url,
                                      member_payinfo.key_pem)
            return {'data': resp, 'status': 200}
        if results['xml']['return_code'] == 'SUCCESS':
            if results['xml']['result_code'] == 'SUCCESS':
                ev_pod_door_log_out.money = money
                ev_pod_door_log_out.pay_type = 4
                ev_pod_door_log_out.update()
                return {'data': data, 'status': 200}
            else:
                return_msg = results['xml']['return_msg']
        else:
            return_msg = results['xml']['return_msg']
        return {'return_msg': return_msg, 'status': 400}
    except BaseException:
        return {'msg': '支付异常', 'status': 400}




def door_refund(ev_pod_door_logs,user,ev_note):
    '''门禁退款'''
    doorin_time = timer.time2timestamp(ev_pod_door_logs[0].add_time.strftime("%Y-%m-%d %H:%M:%S"))  # 进门时间
    doorout_time = time.time()  # 出门时间
    if doorout_time - doorin_time < ev_note.free_time * 60:  # 在免费充电时长内
        ev_pod_door_logs_fefund = ev_pod_door_logs[0]
        if ev_pod_door_logs_fefund.pay_status == 2:  # 已付款
            residue_money = ev_pod_door_logs_fefund.money  # 退款金额
            if ev_pod_door_logs_fefund.pay_type == 3:
                # 退余额
                user.balance += residue_money
                ev_pod_door_logs_fefund.residue_money = residue_money
                ev_pod_door_logs_fefund.refund_time = timer.get_now()
                ev_pod_door_logs_fefund.pay_status = 3
                ev_pod_door_logs_fefund.is_invalid = 1  #分成失效
                ev_pod_door_logs_fefund.update()
                user.update()
                #分成冻结
                sob_handle = sob.sql_open(db_config)
                value_info = {
                    'mini_id': ev_pod_door_logs_fefund.mini_id,
                    'note_id': ev_pod_door_logs_fefund.note_id,
                    'user_id': ev_pod_door_logs_fefund.user_id,
                    'scene': 40,
                    'type': 2,
                    'start_time': str(ev_pod_door_logs_fefund.add_time),
                    'end_time': timer.get_now(),
                    'money': ev_pod_door_logs_fefund.residue_money,
                    'describes': '门禁退款到余额',
                    'add_time': timer.get_now()
                }
                sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_user_balance_log', [value_info])
                sob.sql_close(sob_handle)

                try:
                    ev_dealer_order = Ev_dealer_order.findAll('mini_id=? and order_id=?',[ev_pod_door_logs_fefund.mini_id, ev_pod_door_logs_fefund.id])
                    for order in ev_dealer_order:
                        order.is_invalid = 1  # 失效
                        order.update()
                    if ev_pod_door_logs_fefund.is_settled == 1:
                        # 已结算
                        ev_dealer_orders = Ev_dealer_order.findAll('note_id=? and order_id=? and is_settled=1',
                                                                         [ev_pod_door_logs_fefund.note_id, ev_pod_door_logs_fefund.id])
                        for dealer in ev_dealer_orders:
                            ev_dealer_note = (Ev_dealer_note.findAll('account_id=?', [dealer.account_id]))[0]
                            ev_dealer_note.money -= dealer.share_money
                            ev_dealer_note.update()
                except:
                    prolog.error('code:2006:结算回退出错')
            elif ev_pod_door_logs[0].pay_type == 4:
                # 退微信
                member_miniapp = Member_miniapp.find(ev_pod_door_logs_fefund.mini_id)
                member_payinfo = Member_payinfo.findAll('mini_id=?', [ev_pod_door_logs_fefund.mini_id])[0]
                out_refund_no = datetime.datetime.today().strftime('%Y%m%d%H%M%S') + str(
                    ev_pod_door_logs_fefund.user_id)
                refund_fee = int(residue_money * 100)
                total_fee = int(residue_money * 100)
                try:
                    if member_payinfo.pay_type == 1:
                        notify_url = f'{REQ_HOST}/api/wx_door_fefunds_payback/{member_payinfo.orgid}'
                        wx_pay_sdk().refunds_v3(
                            ev_pod_door_logs_fefund.transaction_id,
                            out_refund_no,
                            refund_fee,
                            total_fee,
                            member_payinfo.mchid,
                            member_payinfo.apikey,
                            member_payinfo.key_pem,
                            notify_url)
                    else:
                        tl_pay = tl_pay_sdk()
                        resp = tl_pay.tl_refunds(member_payinfo.orgid, member_payinfo.mchid, member_payinfo.apikey,
                                                 refund_fee, out_refund_no,
                                                 ev_pod_door_logs_fefund.transaction_id,
                                                 member_payinfo.key_pem)
                        if resp['retcode'] == 'SUCCESS':
                            if resp['trxstatus'] == '0000':
                                trxid = resp['trxid']  # 收银宝交易单号
                                ev_pod_door_logs_fefund.residue_money = residue_money
                                ev_pod_door_logs_fefund.refund_id = trxid
                                ev_pod_door_logs_fefund.refund_time = timer.get_now()
                                ev_pod_door_logs_fefund.pay_status = 3
                                ev_pod_door_logs_fefund.is_invalid = 1  # 分成失效
                                ev_pod_door_logs_fefund.update()
                                # 分成冻结
                                sob_handle = sob.sql_open(db_config)
                                value_info = {
                                    'mini_id': ev_pod_door_logs_fefund.mini_id,
                                    'note_id': ev_pod_door_logs_fefund.note_id,
                                    'user_id': ev_pod_door_logs_fefund.user_id,
                                    'scene': 40,
                                    'type': 2,
                                    'start_time': str(ev_pod_door_logs_fefund.add_time),
                                    'end_time': timer.get_now(),
                                    'money': ev_pod_door_logs_fefund.residue_money,
                                    'describes': '门禁退款到通联',
                                    'add_time': timer.get_now()
                                }
                                sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_user_balance_log',
                                                                           [value_info])
                                sob.sql_close(sob_handle)
                                try:
                                    ev_dealer_order = Ev_dealer_order.findAll('mini_id=? and order_id=?',
                                                                              [ev_pod_door_logs_fefund.mini_id,
                                                                               ev_pod_door_logs_fefund.id])
                                    for order in ev_dealer_order:
                                        order.is_invalid = 1  # 失效
                                        order.update()
                                    if ev_pod_door_logs_fefund.is_settled == 1:
                                        # 已结算
                                        ev_dealer_orders = Ev_dealer_order.findAll(
                                            'note_id=? and order_id=? and is_settled=1',
                                            [ev_pod_door_logs_fefund.note_id, ev_pod_door_logs_fefund.id])
                                        for dealer in ev_dealer_orders:
                                            ev_dealer_note = (Ev_dealer_note.findAll('clerk_id=?', [dealer.user_id]))[0]
                                            ev_dealer_note.money -= dealer.share_money
                                            ev_dealer_note.update()
                                except:
                                    prolog.error('code:2006:结算回退出错')
                    ev_pod_door_logs_fefund.residue_money = residue_money
                    ev_pod_door_logs_fefund.update()
                except:
                    prolog.error('code:2007:退款异常')


if __name__ == '__main__':
    udp_server = UdpServer()
    udp_server.start()


# 1.引入相关
# 2.数据库有用到的表，model
# 3.mini_id----mini_id
# 4.支付---修改
# 5.id,save()
# 6.字段检查，时间等的判断

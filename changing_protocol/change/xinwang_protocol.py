import binascii
import secrets
import time

from change.normal_query import get_setting, get_access_token, start_rechage_send_tempalte, invalid_dealer_order, \
    five_order_refund, over_recharge, shua_card_rechage,xwcalc_consum
from config import db_config
from tool.calc import low_high, dec2hex, getimestamp
from tool.logger import MyLogger
from tool.wf_mysql import wf_mysql_class
from tool.wf_time_new import wf_time_new
from tool.wx_sdk import tl_pay_sdk, wx_pay_sdk

prolog = MyLogger("main", level=20).logger
sob = wf_mysql_class(cursor_type=True)
timer = wf_time_new()

def xinwang_protocol(data, conn, addr):
    byte_len = int(data[8:10], 16) * 2
    if byte_len == len(data):
        cmd = data[10:12]
        # 唯一标记 onlytag
        onlytag = data[12:20]
        prolog.info(f'onlytag:{onlytag},len:{len(onlytag)}')
        # 服务标记 servertag
        servertag = data[20:28]
        if cmd == '20':  #握手
            cmddata = data[28:]  # 指令数据
            serialnum = int(low_high(cmddata[0:16]), 16)  # 充电桩串号
            pileversion = int(low_high(cmddata[16:24]), 16)  # 充电桩版本
            iccid = binascii.a2b_hex(cmddata[24:66]).decode()  # ICCID号码

            # 默认握手返回参数
            fullelectric = 60
            endelectric = 20
            piletype = 1
            pileheart = 60

            #充电桩数据入库
            sob_handle = sob.sql_open(db_config)
            cmd = f"""
            update wxapp_pod_pile set lastip="{addr}",pileversion='{pileversion}',iccid='{iccid}',
            isonline=1,snum='{serialnum}',type=1,update_time='{timer.get_now()}'
            where serialnum='{serialnum}'
            """
            sob.update_mysql_record(sob_handle,cmd)
            sob.sql_close(sob_handle)

            repheard = 'dddd'
            repcheck = '0'.zfill(4)
            repcmd = '01'
            redata = onlytag + low_high(dec2hex(5000).zfill(4)) + low_high(
                dec2hex(fullelectric).zfill(4)) + low_high(dec2hex(180).zfill(
                4)) + low_high(dec2hex(300).zfill(4)) + low_high(dec2hex(3600).zfill(4)) + low_high(
                dec2hex(endelectric).zfill(4)) + low_high(dec2hex(20).zfill(4)) + dec2hex(piletype).zfill(2) + '0'.zfill(20) + low_high(
                dec2hex(pileheart).zfill(4)) + dec2hex(5).zfill(2) + dec2hex(5).zfill(2)
            replen = (len(redata) + 28) / 2
            replen = dec2hex(replen).zfill(2)
            repmsg = repheard + repcheck + replen + repcmd + onlytag + servertag + redata
            prolog.info('握手成功返回消息 resp data:{}'.format(repmsg))
            repsend = binascii.a2b_hex(repmsg)
            conn.send(repsend)
        elif cmd == '02':  #心跳上报
            repheard = 'dddd'
            repcheck = '0'.zfill(4)
            repcmd = '03'
            snumber = data[28:44]  # 充电桩串号
            serialnum = int(low_high(data[28:44]), 16)  # 充电桩串号
            repcode = '01'  # 01 认证成功 02认证失败
            timestamp = getimestamp() #时间戳 8byte
            redata = snumber + repcode + timestamp
            replen = (len(redata) + 28) / 2
            replen = dec2hex(replen).zfill(2)
            repmsg = repheard + repcheck + replen + repcmd + onlytag + servertag + redata
            prolog.info(f'身份验证回复 resp data:{repmsg}')
            repsend = binascii.a2b_hex(repmsg)
            conn.send(repsend)
            sob_handle = sob.sql_open(db_config)
            cmd = f"""update wxapp_pod_pile set lastip="{addr}",isonline=1,snum='{serialnum}',type=1,update_time='{timer.get_now()}'
                    where serialnum='{serialnum}'
                    """
            sob.update_mysql_record(sob_handle, cmd)
            cmd = f"select * from wxapp_order where snum='{serialnum}' and order_status=10"
            orders_ing = sob.select_mysql_record(sob_handle,cmd)
            sob.sql_close(sob_handle)
            for order in orders_ing:
                onlytag = secrets.token_hex(4)
                servertag = '0'.zfill(8)
                repheard = 'dddd'
                repcheck = '0'.zfill(4)
                # 指令数据
                repcmd = '08'
                # 指令 0x01 继电器闭合 0x02 继电器断开
                if int(order['billtype']) != 2:
                    pattern = '2'.zfill(2)
                    duration = int(order['recharge_time']) * 60 - int((time.time() - timer.time2timestamp(order['start_time'].strftime("%Y-%m-%d %H:%M:%S"))) / 60)  # 续充分钟数
                    if duration < 0:
                        duration = 5
                    threshold = '0'
                else:
                    pattern = '1'.zfill(2)
                    duration = 10
                    threshold = dec2hex(int(130))
                port = dec2hex(int(order['portnum'])).zfill(2)
                duration = dec2hex(duration)
                cmd = '01'.zfill(2)
                redata = onlytag[:4] + port + cmd + pattern + \
                         low_high(duration.zfill(4)) + low_high(threshold.zfill(4))
                replen = (len(redata) + 28) / 2
                replen = dec2hex(replen).zfill(2)
                time.sleep(2)
                repmsg = repheard + repcheck + replen + repcmd + onlytag + servertag + redata
                prolog.info(f'断电续充 resp data:{repmsg}')
                repsend = binascii.a2b_hex(repmsg)
                conn.send(repsend)
        elif cmd == '04': #端口状态定时上报指令
            iport = int(data[32:34], 16)  # 端口数量
            sob_handle = sob.sql_open(db_config)
            cmd = f"""select * from wxapp_pod_pile where lastip="{addr}"
            """
            pod_pile = sob.select_mysql_record(sob_handle,cmd)
            if pod_pile:
                pod_pile = pod_pile[0]
                cmd = f"update wxapp_pod_pile set pileport={iport},isonline=1,update_time='{timer.get_now()}' where id={pod_pile['id']}"
                sob.update_mysql_record(sob_handle,cmd)
                for i in range(1, iport + 1):
                    pdata = data[(i - 1) * 18 + 34:(i) * 18 + 34]
                    portnum = int(pdata[0:2], 16)  # 端口内部编号
                    portvoltage = int(pdata[2:4], 16)
                    portelectric = int(low_high(pdata[4:8]), 16)
                    portpulse = int(low_high(pdata[8:16]), 16)
                    portstatus = pdata[16:]  # 01:闭合 02:断开
                    portstatus = 1 if portstatus == '01' else 0
                    value_info = {
                        "pile_id":pod_pile['id'],
                        "serialnum":pod_pile['serialnum'],
                        "portnum":portnum,
                        "portstatus":portstatus,
                        "portvoltage":portvoltage,
                        "portelectric":portelectric,
                        "portpulse":portpulse,
                        "mini_id":pod_pile['mini_id'],
                        "note_id":pod_pile['note_id'],
                    }
                    hope_value = value_info.keys()
                    cmd = f"select * from wxapp_pod_pileport where pile_id={pod_pile['id']} and portnum={portnum}"
                    pileport_info = sob.select_mysql_record(sob_handle,cmd)
                    if pileport_info:
                        value_info.update({'id':pileport_info[0]['id']})
                    sob.insert_Or_update_mysql_record_many_new(sob_handle,'wxapp_pod_pileport',[value_info],hope_value)
                    try:
                        if portelectric > 0:
                            table_name = f'wxapp_pod_port_electric_{timer.get_day()}'
                            table_name = table_name.replace('-', '_')
                            value_info = {
                                "mini_id":pod_pile['mini_id'],
                                "pile_id":pod_pile['id'],
                                "serialnum":pod_pile['serialnum'],
                                "portnum":portnum,
                                "portvoltage":portvoltage,
                                "portelectric":portelectric,
                                "portpulse":portpulse,
                                "add_time":timer.get_now()
                            }
                            sob.insert_Or_update_mysql_record_many_new(sob_handle,table_name,[value_info])
                    except Exception as e:
                        prolog.error(f'新网电流数据入库失败,error:{e}')
            sob.sql_close(sob_handle)
            # 回复 指令
            repheard = 'dddd'
            repcheck = '0'.zfill(4)
            repcmd = '05'
            repcode = '01'  # 01 收到定时状态上报
            redata = repcode
            replen = (len(redata) + 28) / 2
            replen = dec2hex(replen).zfill(2)
            repmsg = repheard + repcheck + replen + repcmd + onlytag + servertag + redata
            prolog.info(f'端口状态上报指令回复 resp data:{repmsg}')
            repsend = binascii.a2b_hex(repmsg)
            conn.send(repsend)
        elif cmd == '06': #充电桩端口状态上报指令
            portnum = data[30:32]
            portvoltage = int(data[32:34], 16)
            portelectric = int(data[34:38], 16)
            portstatus = data[38:40]  # 充电端口继电器状态
            portpulse = int(low_high(data[42:]), 16)
            portstatus = 1 if portstatus == '01' else 0
            sob_handle = sob.sql_open(db_config)
            cmd = f"""select * from wxapp_pod_pile where lastip="{addr}"
            """
            pod_pile = sob.select_mysql_record(sob_handle, cmd)
            if pod_pile:
                pod_pile = pod_pile[0]
                cmd = f"""update wxapp_pod_pileport set portvoltage={portvoltage},portelectric={portelectric},
                portpulse='{portpulse}',portstatus={portstatus} where pile_id={pod_pile['id']} and portnum={int(portnum,16)}"""
                sob.update_mysql_record(sob_handle, cmd)
            sob.sql_close(sob_handle)
            # 回复 指令
            repheard = 'dddd'
            repcheck = '0'.zfill(4)
            repcmd = '07'
            repcode = '01'  # 01 收到定时状态上报
            redata = repcode + portnum
            replen = (len(redata) + 28) / 2
            replen = dec2hex(replen).zfill(2)
            repmsg = repheard + repcheck + replen + repcmd + onlytag + servertag + redata
            prolog.info(f'端口状态上报指回复 resp data:{repmsg}')
            repsend = binascii.a2b_hex(repmsg)
            conn.send(repsend)
        elif cmd == '09': #充电桩端口控制指令 回复
            onlytag = data[28:32]
            portnum = int(data[32:34], 16)
            portstatus = data[34:36]  # 01 闭合成功 02闭合失败 03继电器断开成功 04继电器断开失败
            sob_handle = sob.sql_open(db_config)
            cmd = f"""select a.*,note_name,open_id from wxapp_order a left join wxapp_user b on a.user_id=b.id
            left join wxapp_note c on a.note_id=c.id
            where onlytag='{onlytag}' and portnum={portnum} and order_status=1 order by a.add_time desc"""
            orders = sob.select_mysql_record(sob_handle,cmd)
            if orders:
                order = orders[0]
                if portstatus == '01': #充电成功
                    cmd = f"update wxapp_order set order_status=10 where id={order['id']}"
                    sob.update_mysql_record(sob_handle,cmd)
                    values_json = get_setting(order['mini_id'], 'submsg')
                    if values_json:
                        template_id = values_json['order']['recharge_start']['template_id']
                        access_token = get_access_token(order['mini_id'])
                        start_rechage_send_tempalte(access_token, order,template_id)
                else: #充电失败
                    cmd = f"update wxapp_order set order_status=30,end_time='{timer.get_now()}' where id={order['id']}"
                    sob.update_mysql_record(sob_handle, cmd)
                    cmd = f"update wxapp_pod_pileport set portstatus=0 where id={order['pileport_id']}"
                    sob.update_mysql_record(sob_handle, cmd)
                    five_order_refund(order)
            sob.sql_close(sob_handle)

        elif cmd == '10':
            portnum = int(data[28:30], 16)
            portstatus = data[30:32]  # 01 闭合 02断开
            portstatus = 1 if portstatus == '01' else 0
            sob_handle = sob.sql_open(db_config)
            cmd = f"""select * from wxapp_pod_pile where lastip="{addr}"
            """
            pod_pile = sob.select_mysql_record(sob_handle, cmd)
            if pod_pile:
                pod_pile = pod_pile[0]
                cmd = f"update wxapp_pod_pileport set portstatus={portstatus} where pile_id={pod_pile['id']} and portnum={portnum}"
                sob.update_mysql_record(sob_handle, cmd)
            sob.sql_close(sob_handle)
            repheard = 'dddd'
            repcheck = '0'.zfill(4)
            repcmd = '11'
            snumber = data[28:30]
            repcode = '01'  # 01 认证成功 02认证失败
            redata = snumber + repcode
            replen = (len(redata) + 28) / 2
            replen = dec2hex(replen).zfill(2)
            repmsg = repheard + repcheck + replen + repcmd + onlytag + servertag + redata
            prolog.info(f'充电桩端触发指令 resp data:{repmsg}')
            repsend = binascii.a2b_hex(repmsg)
            conn.send(repsend)

        elif cmd == '0a': #充电桩刷卡状态上报
            portnum = data[28:30]
            cardno = data[30:50]
            cardnohex = binascii.a2b_hex(cardno).decode()
            sob_handle = sob.sql_open(db_config)
            cmd = f"""select * from wxapp_pod_pile where lastip="{addr}"
            """
            pod_pile = sob.select_mysql_record(sob_handle, cmd)
            if pod_pile:
                onlytags = secrets.token_hex(4)  # 唯一标识
                repcode, lastrowid = shua_card_rechage(pod_pile, cardnohex, int(portnum,16), onlytags)
                # repcode = '01'  # 01 卡正常 02 卡无效 ... 07 参考返回代码
                repheard = 'dddd'
                repcheck = '0'.zfill(4)
                repcmd = '0B'
                redata = portnum + cardno.zfill(20) + repcode
                replen = (len(redata) + 28) / 2
                replen = dec2hex(replen).zfill(2)
                repmsg = repheard + repcheck + replen + repcmd + onlytag + servertag + redata
                prolog.info(f'充电桩刷卡状态 resp data:{repmsg}')
                repsend = binascii.a2b_hex(repmsg)
                conn.send(repsend)
                if repcode == '01':
                    # 下发端口控制指令
                    servertag = '0'.zfill(8)
                    repheard = 'dddd'
                    repcheck = '0'.zfill(4)
                    # 指令数据
                    repcmd = '08'
                    # 指令 0x01 继电器闭合 0x02 继电器断开
                    port = portnum.zfill(2)
                    cmd = '1'.zfill(2)
                    pattern = '01'.zfill(2)
                    threshold = dec2hex(int(130))
                    redata = onlytags[:4] + port + cmd + pattern + \
                             '0'.zfill(4) + low_high(threshold.zfill(4))
                    replen = (len(redata) + 28) / 2
                    replen = dec2hex(replen).zfill(2)
                    repmsg = repheard + repcheck + replen + repcmd + onlytags + servertag + redata
                    prolog.info(f'下发端口控制指令 resp data:{repmsg}')
                    try:
                        repsend = binascii.a2b_hex(repmsg)
                        conn.send(repsend)
                    except:
                        cmd = f"delect from wxapp_order where id={lastrowid}"
                        sob.delete_mysql_record(sob_handle,cmd)
            sob.sql_close(sob_handle)

        elif cmd == '0e': #充电桩充电结束上报
            portnum = data[28:30]
            portendstatue = data[30:32]  # 充电结束代码 01 充电头被拔 ... 07..
            powerwaste = int(data[32:36], 16)  # 功耗 N/3200度
            porttag = int(data[36:40], 16)  # 端口标记
            portelectric = int(low_high(data[40:44]), 16)  # 判断电流 结束时的电流
            portpulse = int(low_high(data[44:]), 16)  # 脉冲数值
            sob_handle = sob.sql_open(db_config)
            cmd = f"""select * from wxapp_pod_pile where lastip="{addr}"
            """
            pod_pile = sob.select_mysql_record(sob_handle, cmd)
            if pod_pile:
                pod_pile = pod_pile[0]
                cmd = f"select * from wxapp_order where snum='{pod_pile['snum']}' and portnum={int(portnum, 16)} and (order_status=10 or order_status=11) and add_time>'{timer.get_now_bef_aft(hours=24,is_trans=True)}' order by add_time desc"
                orders = sob.select_mysql_record(sob_handle,cmd)
                if orders:
                    order = orders[0]
                    end_time = timer.get_now()
                    order['end_time'] = end_time
                    # 计算充电时间判断是否大于5分钟
                    rechargetime = (timer.time2timestamp(order['end_time']) - timer.time2timestamp(order['start_time'].strftime("%Y-%m-%d %H:%M:%S"))) / 60  # 分钟
                    #结束充电
                    consum_elec = xwcalc_consum(order)
                    over_recharge(order,rechargetime,end_time,portendstatue,powerwaste,portelectric,consum_elec)
            # 回复指令
            repheard = 'dddd'
            repcheck = '0'.zfill(4)
            repcmd = '0F'
            repcode = '01'  # 01
            redata = portnum + repcode
            replen = (len(redata) + 28) / 2
            replen = dec2hex(replen).zfill(2)
            repmsg = repheard + repcheck + replen + repcmd + onlytag + servertag + redata
            prolog.info(f'充电结束并回复指令 resp data:{repmsg}')
            repsend = binascii.a2b_hex(repmsg)
            conn.send(repsend)
            sob.sql_close(sob_handle)














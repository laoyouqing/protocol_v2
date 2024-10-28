import binascii
import datetime

from change.normal_query import over_recharge, shua_card_rechage, get_setting, get_access_token, \
    start_rechage_send_tempalte, five_order_refund
from config import db_config
from tool.bkv import unpack, pack
from tool.calc import dec2hex, uchar_checksum, low_high
from tool.logger import MyLogger
from tool.wf_mysql import wf_mysql_class
from tool.wf_time_new import wf_time_new

prolog = MyLogger("main", level=20).logger
sob = wf_mysql_class(cursor_type=True)
timer = wf_time_new()

def bolai_protocol(data, conn, addr):
    old_data = data
    cklen = data[4:8]  # 去字符串长度
    # 字符串长度 * 2
    cklen = int(cklen, 16) * 2 + 8  # fcfe 包头长度
    index = data.split('fcee')
    data_pile = ''
    if len(index) > 2:
        index = data.find('fcee')
        data_pile = data[index + 4:]
        data = data[:index + 4]
    print('--------------')
    # 2. 校验字符串长度都 2byte
    if cklen == len(data):
        # 唯一标记 onlytag 网关ID
        onlytag = data[22:36]
        # 3. cmd指令 1byte
        cmd = data[8:12]
        prolog.info(f'cmd:{cmd}')
        sob_handle = sob.sql_open(db_config)
        value_info = {
            "data": old_data,
            "onlytag": onlytag,
            "cmd": cmd,
            "add_time": timer.get_now()
        }
        sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_protocol_log', [value_info])
        sob.sql_close(sob_handle)
        if cmd == '0000':
            # 心跳上报 命令0
            version = binascii.a2b_hex(data[76:92])
            xhqd = int(data[92:94], 16)
            prolog.info(f'信号强度:{xhqd}')
            sob_handle = sob.sql_open(db_config)
            cmd = f"""update wxapp_pod_pile set xhqd='{xhqd}',pileversion="{sob.escape(version)}",lastip="{addr}",update_time='{timer.get_now()}',isonline=1 where gateway_id='{onlytag}'"""
            prolog.info(cmd)
            sob.update_mysql_record(sob_handle,cmd)
            sob.sql_close(sob_handle)
            repheard = 'fcff'
            nowtime = datetime.datetime.now()
            repdatetime = nowtime.strftime("%Y%m%d%H%M%S")
            # 命令 + 流水号(设备主动上报帧流水号为 0) + 回复包类型 00(数据包方向00下发 01上行)
            repcmd = '0000' + '0'.zfill(8) + '00'
            redata = repcmd + onlytag + repdatetime
            # 6 = 校验00 + 包尾fcee
            replen = (len(redata) + 6) / 2
            replen = dec2hex(replen).zfill(4)
            cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen +redata))).zfill(2).lower()

            repmsg = repheard + replen + redata + cksum + 'fcee'
            prolog.info(f'心跳上报:{onlytag} resp data:{repmsg}')
            repsend = binascii.a2b_hex(repmsg)
            conn.send(repsend)
        elif cmd == '0015':
            # 子命令
            childcmd = data[40:42]
            # 唯一标记 onlytag 网关ID
            onlytag = data[22:36]
            # 第n号插座
            plugnum = int(data[42:44], 16)
            plug_num = data[42:44]
            # 插座软件版本
            plugversion = data[44:48]
            if childcmd == '1c':
                # 插座状态上报 指令
                # 计算孔数
                data_len = len(data[52:])
                num = (data_len - 6) / 28
                sob_handle = sob.sql_open(db_config)
                cmd = f"select * from wxapp_pod_pile where gateway_id='{onlytag}' and serialnum='{plugnum}'"
                pod_pile = sob.select_mysql_record(sob_handle, cmd)
                if pod_pile:
                    pod_pile = pod_pile[0]
                    cmd = f"""update wxapp_pod_pile set pileport={int(num)},lastip="{addr}" where id={pod_pile['id']}"""
                    sob.update_mysql_record(sob_handle,cmd)
                    for i in range(0, int(num)):
                        # 孔
                        pile = int(data[52 + i * 28:54 + i * 28], 16)
                        # 插座状态
                        plugstatus = data[54 + i * 28:56 + i * 28]
                        if plugstatus == '80':
                            plugstatus = 0
                        else:
                            plugstatus = 1
                        # 电压
                        voltage = int(data[60 + i * 28:64 + i * 28], 16)  # 十六进制转十进制
                        # 功率
                        power = int(data[64 + i * 28:68 + i * 28], 16)
                        # 电流
                        electric = int(data[68 + i * 28:72 + i * 28], 16)
                        # 用电量
                        consum_elec = int(data[72 + i * 28:76 + i * 28], 16)
                        # 充电时间
                        chargetime = int(data[76 + i * 28:80 + i * 28], 16)
                        value_info = {
                            "pile_id": pod_pile['id'],
                            "serialnum": pod_pile['serialnum'],
                            "portnum": i,
                            "portstatus": plugstatus,
                            "portvoltage": voltage,
                            "portelectric": electric,
                            "mini_id": pod_pile['mini_id'],
                            "note_id": pod_pile['note_id'],
                        }
                        hope_value = value_info.keys()
                        cmd = f"select * from wxapp_pod_pileport where pile_id={pod_pile['id']} and portnum={int(pile)}"
                        pileport_info = sob.select_mysql_record(sob_handle, cmd)
                        if pileport_info:
                            value_info.update({'id': pileport_info[0]['id']})
                        sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_pod_pileport', [value_info],hope_value)
                        try:
                            if electric > 0:
                                table_name = f'wxapp_pod_port_electric_{timer.get_day()}'
                                table_name = table_name.replace('-', '_')
                                value_info = {
                                    "mini_id": pod_pile['mini_id'],
                                    "pile_id": pod_pile['id'],
                                    "serialnum": pod_pile['serialnum'],
                                    "portnum": i,
                                    "portvoltage": voltage,
                                    "portelectric": electric,
                                    "portpulse": power,
                                    "power": consum_elec,
                                    "rechargetime": chargetime,
                                    "add_time": timer.get_now()
                                }
                                sob.insert_Or_update_mysql_record_many_new(sob_handle, table_name, [value_info])
                        except Exception as e:
                            prolog.error(f'新网电流数据入库失败,error:{e}')
                sob.sql_close(sob_handle)

                repheard = 'fcff'
                # 命令 + 流水号(设备主动上报帧流水号为 0) + 回复包类型 00(数据包方向00下发 01上行)
                repcmd = '0015' + '0'.zfill(8) + '00'
                redata = repcmd + onlytag + '0003' + '1c' + plug_num + '01'
                # 6 = 校验00 + 包尾fcee
                replen = (len(redata) + 6) / 2
                replen = dec2hex(replen).zfill(4)
                cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen +redata))).zfill(2).lower()
                repmsg = repheard + replen + redata + cksum + 'fcee'
                prolog.info('插座状态上报：onlytag:{} plugnum:{} resp data:{}'.format(onlytag, plugnum, repmsg))
                repsend = binascii.a2b_hex(repmsg)
                conn.send(repsend)
            elif childcmd == '02':
                # 充电结束上报(按时/按电量)
                # 插孔号
                pile = int(data[52:54], 16)
                # 插座状态
                plugstatus = data[54:56]
                # 功率
                power = int(data[60:64], 16)
                # 电流
                electric = int(data[64:68], 16)
                sob_handle = sob.sql_open(db_config)
                cmd = f"select * from wxapp_pod_pile where gateway_id='{onlytag}' and serialnum='{plugnum}'"
                pod_pile = sob.select_mysql_record(sob_handle, cmd)
                if pod_pile:
                    pod_pile = pod_pile[0]
                    cmd = f"select * from wxapp_order where snum='{pod_pile['snum']}' and portnum={int(pile)} and (order_status=10 or order_status=11) and add_time>'{timer.get_now_bef_aft(hours=24,is_trans=True)}' order by add_time desc"
                    orders = sob.select_mysql_record(sob_handle, cmd)
                    if orders:
                        order = orders[0]
                        end_time = timer.get_now()
                        order['end_time'] = end_time
                        # 计算充电时间判断是否大于5分钟
                        rechargetime = (timer.time2timestamp(order['end_time']) - timer.time2timestamp(
                            order['start_time'].strftime("%Y-%m-%d %H:%M:%S"))) / 60  # 分钟
                        # 结束充电
                        over_recharge(order, rechargetime, end_time, plugstatus, power, electric)
                sob.sql_close(sob_handle)
                # 回复指令
                repheard = 'fcff'
                # 命令 + 流水号(设备主动上报帧流水号为 0) + 回复包类型 00(数据包方向00下发 01上行)
                repcmd = '0015' + '0'.zfill(8) + '00'
                redata = repcmd + onlytag + '0003' + '02' + plug_num + '01'
                # 6 = 校验00 + 包尾fcee
                replen = (len(redata) + 6) / 2
                replen = dec2hex(replen).zfill(4)
                cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen +redata))).zfill(2).lower()
                repmsg = repheard + replen + redata + cksum + 'fcee'
                prolog.info('充电结束上报(按时/按电量) resp data:{}'.format(repmsg))
                repsend = binascii.a2b_hex(repmsg)
                conn.send(repsend)
            elif childcmd == '0b':
                # 刷卡充电(按时/按量)
                prolog.info('刷卡充电--------')
                # 插孔号
                pile = data[44:46]
                portnum = int(pile, 16)
                # 业务号
                bussno = data[46:50]
                # 卡号长度
                cardid = data[52:64]
                cardlen = cardid[-8:]
                cardlen = str(int(low_high(cardlen), 16)).zfill(10)
                # 请求接口判断卡片是否可用并下发充电命令#######
                sob_handle = sob.sql_open(db_config)
                cmd = f"select * from wxapp_pod_pile where gateway_id='{onlytag}' and serialnum='{plugnum}'"
                pod_pile = sob.select_mysql_record(sob_handle, cmd)
                if pod_pile:
                    repcode,lastrowid = shua_card_rechage(pod_pile, cardlen, portnum, onlytag,piletype=2)
                    if repcode == '01':
                        repheard = 'fcff'
                        # 命令 + 流水号(设备主动上报帧流水号为 0) + 回复包类型 00(数据包方向00下发 01上行)
                        duration = dec2hex(720)
                        repcmd = '0015' + '0028373f' + '00'
                        repsms = '000a' + childcmd + plug_num + pile + \
                                 bussno + '01' + '01' + duration.zfill(4) + '0000'
                        repdata = repcmd + onlytag + repsms
                        replen = (len(repdata) + 6) / 2
                        replen = dec2hex(replen).zfill(4)
                        cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen +repdata))).zfill(2).lower()
                        repmsg = repheard + replen + repdata + cksum + 'fcee'
                        prolog.info('刷卡充电 resp data:{}'.format(repmsg))
                        try:
                            repsend = binascii.a2b_hex(repmsg)
                            conn.send(repsend)
                        except:
                            cmd = f"delect from wxapp_order where id={lastrowid}"
                            sob.delete_mysql_record(sob_handle, cmd)
                sob.sql_close(sob_handle)
            elif childcmd == '0c':
                # 刷卡充电结束(按时/按量)
                # 插孔号
                pile = data[52:54]
                # 插座状态
                plugstatus = data[54:56]
                # 功率
                power = int(data[60:64], 16)
                # 电流
                electric = int(data[64:68], 16)
                sob_handle = sob.sql_open(db_config)
                cmd = f"select * from wxapp_pod_pile where gateway_id='{onlytag}' and serialnum='{plugnum}'"
                pod_pile = sob.select_mysql_record(sob_handle, cmd)
                if pod_pile:
                    pod_pile = pod_pile[0]
                    cmd = f"select * from wxapp_order where snum='{pod_pile['snum']}' and portnum={int(pile,16)} and (order_status=10 or order_status=11) and add_time>'{timer.get_now_bef_aft(hours=24,is_trans=True)}' order by add_time desc"
                    orders = sob.select_mysql_record(sob_handle, cmd)
                    if orders:
                        order = orders[0]
                        end_time = timer.get_now()
                        order['end_time'] = end_time
                        # 计算充电时间判断是否大于5分钟
                        rechargetime = (timer.time2timestamp(order['end_time']) - timer.time2timestamp(
                            order['start_time'].strftime("%Y-%m-%d %H:%M:%S"))) / 60  # 分钟
                        # 结束充电
                        over_recharge(order, rechargetime, end_time, plugstatus, power, electric)
                sob.sql_close(sob_handle)
                repheard = 'fcff'
                # 命令 + 流水号(设备主动上报帧流水号为 0) + 回复包类型 00(数据包方向00下发 01上行)
                repcmd = '0015' + '0'.zfill(8) + '00'
                repsms = '0002' + '0c' + plug_num + '01'
                repdata = repcmd + onlytag + repsms
                replen = (len(repdata) + 6) / 2
                replen = dec2hex(replen).zfill(4)
                cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen +repdata))).zfill(2).lower()
                repmsg = repheard + replen + repdata + cksum + 'fcee'
                prolog.info('刷卡充电结束 resp data:{}'.format(repmsg))
                repsend = binascii.a2b_hex(repmsg)
                conn.send(repsend)
            elif childcmd == '1D':
                # 查询插座状态上报 指令
                # 计算孔数
                sob_handle = sob.sql_open(db_config)
                data_len = len(data[52:])
                num = (data_len - 6) / 28
                for i in range(0, int(num)):
                    # 孔
                    pile = int(data[52 + i * 28:54 + i * 28], 16)
                    # 插座状态
                    plugstatus = binascii.a2b_hex(data[54 + i * 28:56 + i * 28])
                    # 电压
                    voltage = int(data[60 + i * 28:64 + i * 28], 16)  # 十六进制转十进制
                    # 电流
                    electric = int(data[68 + i * 28:72 + i * 28], 16)
                    cmd = f"select * from wxapp_pod_pile where gateway_id='{onlytag}' and serialnum='{plugnum}'"
                    pod_pile = sob.select_mysql_record(sob_handle, cmd)
                    if pod_pile:
                        pod_pile = pod_pile[0]
                        cmd = f"update wxapp_pod_pileport set portvoltage={voltage},portelectric={electric},portstatus={plugstatus} where pile_id={pod_pile['id']} and portnum={int(pile)}"
                        sob.update_mysql_record(sob_handle,cmd)
                    sob.sql_close(sob_handle)
            elif childcmd == '07':
                prolog.info('充电指令回复上报-----')
                status = data[42:44]
                plugnum = int(data[44:46], 16)
                pile = int(data[46:48], 16)
                bussno = data[48:52]
                sob_handle = sob.sql_open(db_config)
                cmd = f"select * from wxapp_pod_pile where gateway_id='{onlytag}' and serialnum='{plugnum}'"
                pod_pile = sob.select_mysql_record(sob_handle, cmd)
                if pod_pile:
                    pod_pile = pod_pile[0]
                    cmd = f"""select a.*,note_name,open_id from wxapp_order a left join wxapp_user b on a.user_id=b.id
                               left join wxapp_note c on a.note_id=c.id
                               where onlytag='{onlytag}' and pile_id={pod_pile['id']} and portnum={pile} and order_status=1
                               order by a.add_time desc
                    """
                    orders = sob.select_mysql_record(sob_handle, cmd)
                    if orders:
                        order = orders[0]
                        if status == '01':  # 充电成功
                            cmd = f"update wxapp_order set order_status=10 where id={order['id']}"
                            sob.update_mysql_record(sob_handle, cmd)
                            values_json = get_setting(order['mini_id'], 'submsg')
                            if values_json:
                                template_id = values_json['order']['recharge_start']['template_id']
                                access_token = get_access_token(order['mini_id'])
                                start_rechage_send_tempalte(access_token, order, template_id)
                        else:  # 充电失败
                            cmd = f"update wxapp_order set order_status=30,end_time='{timer.get_now()}' where id={order['id']}"
                            sob.update_mysql_record(sob_handle, cmd)
                            cmd = f"update wxapp_pod_pileport set portstatus=0 where id={order['pileport_id']}"
                            sob.update_mysql_record(sob_handle, cmd)
                            five_order_refund(order)
                sob.sql_close(sob_handle)
            elif childcmd == '0f':
                print('----------0f------')
                plugnum = int(data[42:44], 16)  # 插座号
                pile = int(data[44:46], 16)  # 插孔号
                status = data[46:48]  # 状态
                sob_handle = sob.sql_open(db_config)
                cmd = f"select * from wxapp_pod_pile where gateway_id='{onlytag}' and serialnum='{plugnum}'"
                pod_pile = sob.select_mysql_record(sob_handle, cmd)
                if pod_pile:
                    pod_pile = pod_pile[0]
                    cmd = f"""
                    select a.*,note_name,open_id from wxapp_order a left join wxapp_user b on a.user_id=b.id
                                                   left join wxapp_note c on a.note_id=c.id
                                                   where onlytag='{onlytag}' and pile_id={pod_pile['id']} and portnum={pile} and order_status=1
                                                   order by a.add_time desc
                    """
                    orders = sob.select_mysql_record(sob_handle, cmd)
                    if orders:
                        order = orders[0]
                        if status == '01':  # 充电成功
                            cmd = f"update wxapp_order set order_status=10 where id={order['id']}"
                            sob.update_mysql_record(sob_handle, cmd)
                            print(cmd)
                        else:
                            cmd = f"update wxapp_order set order_status=30,end_time='{timer.get_now()}' where id={order['id']}"
                            sob.update_mysql_record(sob_handle, cmd)
                            cmd = f"update wxapp_pod_pileport set portstatus=0 where id={order['pileport_id']}"
                            sob.update_mysql_record(sob_handle, cmd)
                            five_order_refund(order)
                sob.sql_close(sob_handle)
        elif cmd == '0005':
            # 下发网络节点列表-
            # 子命令
            childcmd = data[40:42]
        elif cmd == '1000':
            print(data)
            old_xx = data[8:36]
            data = data[36:-6]
            resp = unpack(data)
            key_cmd = resp[0]['key']
            value_cmd = resp[0]['value']
            prolog.info('value_cmd:{}'.format(value_cmd))
            # 帧流水号
            key_framenumber = resp[1]['key']
            value_framenumber = resp[1]['value']
            # 设备网关
            key_mac = resp[2]['key']
            value_mac = resp[2]['value']
            if value_cmd == '1017':
                value_socket_status = resp[3]['value']
                socket_status = unpack(value_socket_status)
                #插座号
                node_number = int(socket_status[0]['value'],16)
                #固件版本
                version = socket_status[1]['value']
                sob_handle = sob.sql_open(db_config)
                cmd = f"select * from wxapp_pod_pile where gateway_id='{onlytag}' and serialnum='{node_number}'"
                pod_pile = sob.select_mysql_record(sob_handle, cmd)
                if pod_pile:
                    pod_pile = pod_pile[0]
                    # 插孔属性
                    for _ in socket_status[4:]:
                        #孔解析
                        pile = unpack(_['value'])
                        # print(pile)
                        # 孔
                        pile_num = int(pile[0]['value'],16)
                        # 插孔状态
                        pile_status = pile[1]['value']
                        # print(pile_status)
                        if pile_status == '80':
                            plugstatus = 0
                        else:
                            plugstatus = 1
                        #电流
                        electric = int(pile[5]['value'],16)
                        value_info = {
                            "pile_id": pod_pile['id'],
                            "serialnum": pod_pile['serialnum'],
                            "portnum": pile_num,
                            "portstatus": plugstatus,
                            "portelectric": electric,
                            "mini_id": pod_pile['mini_id'],
                            "note_id": pod_pile['note_id'],
                        }
                        hope_value = value_info.keys()
                        cmd = f"select * from wxapp_pod_pileport where pile_id={pod_pile['id']} and portnum={pile_num}"
                        pileport_info = sob.select_mysql_record(sob_handle, cmd)
                        if pileport_info:
                            value_info.update({'id': pileport_info[0]['id']})
                        sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_pod_pileport', [value_info],hope_value)
                        try:
                            if electric > 0:
                                table_name = f'wxapp_pod_port_electric_{timer.get_day()}'
                                table_name = table_name.replace('-', '_')
                                value_info = {
                                    "mini_id": pod_pile['mini_id'],
                                    "pile_id": pod_pile['id'],
                                    "serialnum": pod_pile['serialnum'],
                                    "portnum": pile_num,
                                    "portelectric": electric,
                                    "add_time": timer.get_now()
                                }
                                sob.insert_Or_update_mysql_record_many_new(sob_handle, table_name, [value_info])
                        except Exception as e:
                            prolog.error(f'柏莱电流数据入库失败,error:{e}')
                cmd = f"""update wxapp_pod_pile set lastip="{addr}",pileversion='{version}' where gateway_id='{onlytag}' and serialnum='{node_number}'"""
                sob.update_mysql_record(sob_handle, cmd)
                sob.sql_close(sob_handle)
                # 平台回复
                repheard = 'fcff'
                redatalist = [
                    {
                        'key': key_cmd, 'value': value_cmd}, {
                        'key': key_framenumber, 'value': value_framenumber}, {
                        'key': key_mac, 'value': value_mac}, {
                        'key': '0xf', 'value': '01'}]
                redata = ''  # bkv pack数据和
                redata = old_xx  # bkv pack数据和
                for data in redatalist:
                    resp = pack(data)
                    redata += resp
                print(redata)
                # 包长
                replen = (len(redata) + 6) / 2
                replen = dec2hex(replen).zfill(4)
                # 校验和
                cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen + redata))).zfill(2).lower()
                print(cksum)
                repmsg = repheard + replen + redata + cksum + 'fcee'
                prolog.info('两口设备状态上报 resp data:{}'.format(repmsg))
                repsend = binascii.a2b_hex(repmsg)
                conn.send(repsend)

        else:
            btype = 3  # 3柏来十二口
            # bkv解析长度
            old_data = data
            data = data[8:-6]
            resp = unpack(data)
            if resp:
                # 命令
                key_cmd = resp[0]['key']
                value_cmd = resp[0]['value']
                prolog.info('value_cmd:{}'.format(value_cmd))
                # 帧流水号
                key_framenumber = resp[1]['key']
                value_framenumber = resp[1]['value']
                # 设备mac
                key_mac = resp[2]['key']
                value_mac = resp[2]['value']
                if value_cmd == '1001':
                    '''心跳上报/平台回复'''
                    # 版本号
                    key_version = resp[3]['key']
                    value_version = binascii.a2b_hex(resp[3]['value'])
                    prolog.info('value_version:{}'.format(value_version))
                    # 设备信号强度
                    key_signal = resp[4]['key']
                    value_signal = resp[4]['value']
                    # xhqd = binascii.a2b_hex(value_signal)
                    xhqd = int(value_signal, 16)
                    # ICCID
                    key_iccid = resp[5]['key']
                    value_iccid = resp[5]['value']
                    prolog.info('value_iccid:{}'.format(value_iccid))
                    # 平台回复
                    repheard = 'fcff'
                    nowtime = datetime.datetime.now()
                    repdatetime = nowtime.strftime("%Y%m%d%H%M%S")
                    sob_handle = sob.sql_open(db_config)
                    cmd = f"""update wxapp_pod_pile set xhqd='{xhqd}',pileversion="{value_version}",iccid='{value_iccid}',lastip="{addr}",update_time='{timer.get_now()}',isonline=1 where snum='{value_mac}'"""
                    prolog.info(cmd)
                    sob.update_mysql_record(sob_handle, cmd)
                    sob.sql_close(sob_handle)
                    redatalist = [
                        {
                            'key': key_cmd, 'value': value_cmd}, {
                            'key': key_framenumber, 'value': value_framenumber}, {
                            'key': key_mac, 'value': value_mac}, {
                            'key': '0x6', 'value': repdatetime}]
                    redata = ''  # bkv pack数据和
                    for data in redatalist:
                        resp = pack(data)
                        redata += resp
                    # 包长
                    replen = (len(redata) + 6) / 2
                    replen = dec2hex(replen).zfill(4)
                    # 校验和
                    cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen +redata))).zfill(2).lower()
                    repmsg = repheard + replen + redata + cksum + 'fcee'
                    prolog.info('心跳上报回复：value_mac"{} resp data:{}'.format(value_mac, repmsg))
                    repsend = binascii.a2b_hex(repmsg)
                    conn.send(repsend)
                elif value_cmd == '1002':
                    '''设备状态上报/平台回复·'''
                    # 循环孔状态
                    count = 0
                    sob_handle = sob.sql_open(db_config)
                    cmd = f"select * from wxapp_pod_pile where snum='{value_mac}'"
                    pod_pile = sob.select_mysql_record(sob_handle,cmd)
                    if pod_pile:
                        pod_pile = pod_pile[0]
                        for item in resp[4:]:
                            count += 1  # 计算孔数
                            # plug_info 二次解析
                            plug_resp = unpack(item['value'])
                            # 孔
                            key_pile = plug_resp[0]['key']
                            value_pile = int(plug_resp[0]['value'], 16) + 1
                            # 插孔状态
                            key_status = plug_resp[1]['key']
                            value_status = plug_resp[1]['value']
                            if value_status == '80':
                                plugstatus = 0
                            else:
                                plugstatus = 1
                            # 功率
                            key_power = plug_resp[3]['key']
                            value_power = int(plug_resp[3]['value'], 16)
                            # 电流
                            key_electric = plug_resp[4]['key']
                            value_electric = int(plug_resp[4]['value'], 16)
                            # 用电量
                            key_elecon = plug_resp[5]['key']
                            value_elecon = int(plug_resp[5]['value'], 16)
                            # 充电时间
                            key_chargetime = plug_resp[6]['key']
                            value_chargetime = int(plug_resp[6]['value'], 16)
                            # 电压
                            key_press = plug_resp[7]['key']
                            value_press = int(plug_resp[7]['value'], 16)
                            value_info = {
                                "pile_id": pod_pile['id'],
                                "serialnum": pod_pile['serialnum'],
                                "portnum": value_pile,
                                "portstatus": plugstatus,
                                "portvoltage": value_press,
                                "portelectric": value_electric,
                                "mini_id": pod_pile['mini_id'],
                                "note_id": pod_pile['note_id'],
                            }
                            hope_value = value_info.keys()
                            cmd = f"select * from wxapp_pod_pileport where pile_id={pod_pile['id']} and portnum={value_pile}"
                            pileport_info = sob.select_mysql_record(sob_handle, cmd)
                            if pileport_info:
                                value_info.update({'id': pileport_info[0]['id']})
                            sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_pod_pileport', [value_info],hope_value)
                            try:
                                if value_electric > 0:
                                    table_name = f'wxapp_pod_port_electric_{timer.get_day()}'
                                    table_name = table_name.replace('-', '_')
                                    value_info = {
                                        "mini_id": pod_pile['mini_id'],
                                        "pile_id": pod_pile['id'],
                                        "serialnum": pod_pile['serialnum'],
                                        "portnum": value_pile,
                                        "portvoltage": value_press,
                                        "portelectric": value_electric,
                                        "portpulse": value_power,
                                        "power": value_elecon,
                                        "rechargetime": value_chargetime,
                                        "add_time": timer.get_now()
                                    }
                                    sob.insert_Or_update_mysql_record_many_new(sob_handle, table_name, [value_info])
                            except Exception as e:
                                prolog.error(f'柏莱电流数据入库失败,error:{e}')
                    cmd = f"""update wxapp_pod_pile set pileport={count},lastip="{addr}" where snum='{value_mac}'"""
                    sob.update_mysql_record(sob_handle,cmd)
                    sob.sql_close(sob_handle)
                    # 平台回复
                    repheard = 'fcff'
                    redatalist = [
                        {
                            'key': key_cmd, 'value': value_cmd}, {
                            'key': key_framenumber, 'value': value_framenumber}, {
                            'key': key_mac, 'value': value_mac}, {
                            'key': '0xf', 'value': '01'}]
                    redata = ''  # bkv pack数据和
                    for data in redatalist:
                        resp = pack(data)
                        redata += resp
                    # 包长
                    replen = (len(redata) + 6) / 2
                    replen = dec2hex(replen).zfill(4)
                    # 校验和
                    cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen +redata))).zfill(2).lower()
                    repmsg = repheard + replen + redata + cksum + 'fcee'
                    prolog.info('设备状态上报 resp data:{}'.format(repmsg))
                    repsend = binascii.a2b_hex(repmsg)
                    conn.send(repsend)
                elif value_cmd == '1003':
                    '''查询状态设备回复 '''
                    # 循环孔状态
                    count = 0
                    sob_handle = sob.sql_open(db_config)
                    cmd = f"select * from wxapp_pod_pile where snum='{value_mac}'"
                    pod_pile = sob.select_mysql_record(sob_handle, cmd)
                    if pod_pile:
                        pod_pile = pod_pile[0]
                        for item in resp[4:]:
                            count += 1  # 计算孔数
                            # plug_info 二次解析
                            plug_resp = unpack(item['value'])
                            # 孔
                            key_pile = plug_resp[0]['key']
                            value_pile = int(plug_resp[0]['value'], 16)
                            # 插孔状态
                            key_status = plug_resp[1]['key']
                            value_status = plug_resp[1]['value']
                            if value_status == '80':
                                plugstatus = 0
                            else:
                                plugstatus = 1
                            # 订单号
                            key_orderno = plug_resp[2]['key']
                            value_orderno = plug_resp[2]['value']
                            # 功率
                            key_power = plug_resp[3]['key']
                            value_power = int(plug_resp[3]['value'], 16)
                            # 电流
                            key_electric = plug_resp[4]['key']
                            value_electric = int(plug_resp[4]['value'], 16)
                            # 用电量
                            key_elecon = plug_resp[5]['key']
                            value_elecon = plug_resp[5]['value']
                            # 充电时间
                            key_chargetime = plug_resp[6]['key']
                            value_chargetime = plug_resp[6]['value']
                            # 电压
                            key_press = plug_resp[7]['key']
                            value_press = int(plug_resp[7]['value'], 16)
                            value_info = {
                                "pile_id": pod_pile['id'],
                                "serialnum": pod_pile['serialnum'],
                                "portnum": value_pile,
                                "portstatus": plugstatus,
                                "portvoltage": value_press,
                                "portelectric": value_electric,
                                "mini_id": pod_pile['mini_id'],
                                "note_id": pod_pile['note_id'],
                            }
                            hope_value = value_info.keys()
                            cmd = f"select * from wxapp_pod_pileport where pile_id={pod_pile['id']} and portnum={value_pile}"
                            pileport_info = sob.select_mysql_record(sob_handle, cmd)
                            if pileport_info:
                                value_info.update({'id': pileport_info[0]['id']})
                            sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_pod_pileport', [value_info],
                                                                       hope_value)
                    cmd = f"""update wxapp_pod_pile set pileport={count},lastip="{addr}" where snum='{value_mac}'"""
                    sob.update_mysql_record(sob_handle, cmd)
                    sob.sql_close(sob_handle)
                elif value_cmd == '1007':
                    prolog.info('设备控制开关设备回复.....')
                    # 设备控制开关设备回复
                    # 设备回复ok
                    value_reply = resp[3]['value']
                    value_pile = resp[4]['value']
                    busnum = resp[4]['value']  # 业务号
                    sob_handle = sob.sql_open(db_config)
                    cmd = f"""select a.*,note_name,open_id from wxapp_order a left join wxapp_user b on a.user_id=b.id
                                                   left join wxapp_note c on a.note_id=c.id
                                                   where onlytag='{value_mac}' and portnum={int(value_pile,16)+1} and order_status=1
                                                   order by a.add_time desc
                    """
                    orders = sob.select_mysql_record(sob_handle, cmd)
                    if orders:
                        order = orders[0]
                        if value_reply == '01':  # 充电成功
                            cmd = f"update wxapp_order set order_status=10 where id={order['id']}"
                            sob.update_mysql_record(sob_handle, cmd)
                            values_json = get_setting(order['mini_id'], 'submsg')
                            if values_json:
                                template_id = values_json['order']['recharge_start']['template_id']
                                access_token = get_access_token(order['mini_id'])
                                start_rechage_send_tempalte(access_token, order, template_id)
                        else:
                            cmd = f"update wxapp_order set order_status=30,end_time='{timer.get_now()}' where id={order['id']}"
                            sob.update_mysql_record(sob_handle, cmd)
                            cmd = f"update wxapp_pod_pileport set portstatus=0 where id={order['pileport_id']}"
                            sob.update_mysql_record(sob_handle, cmd)
                            five_order_refund(order)

                    sob.sql_close(sob_handle)
                elif value_cmd == '1004':
                    # 充电结束上报（按时）
                    # 插孔号
                    key_pile = resp[4]['key']
                    value_pile = int(resp[4]['value'], 16) + 1
                    # 插孔状态
                    key_status = resp[5]['key']
                    value_status = resp[5]['value']
                    # 当前功率
                    key_power = resp[7]['key']
                    value_power = int(resp[7]['value'], 16)
                    # 当前电流
                    key_electric = resp[8]['key']
                    value_electric = int(resp[8]['value'], 16)
                    sob_handle = sob.sql_open(db_config)
                    cmd = f"select * from wxapp_pod_pile where snum='{value_mac}'"
                    pod_pile = sob.select_mysql_record(sob_handle, cmd)
                    if pod_pile:
                        pod_pile = pod_pile[0]
                        cmd = f"select * from wxapp_order where snum='{pod_pile['snum']}' and portnum={value_pile} and (order_status=10 or order_status=11) and add_time>'{timer.get_now_bef_aft(hours=24,is_trans=True)}' order by add_time desc"
                        orders = sob.select_mysql_record(sob_handle, cmd)
                        if orders:
                            order = orders[0]
                            end_time = timer.get_now()
                            order['end_time'] = end_time
                            # 计算充电时间判断是否大于5分钟
                            rechargetime = (timer.time2timestamp(order['end_time']) - timer.time2timestamp(
                                order['start_time'].strftime("%Y-%m-%d %H:%M:%S"))) / 60  # 分钟
                            # 结束充电
                            over_recharge(order, rechargetime, end_time, value_status, value_power, value_electric)
                            cmd = f"update wxapp_order set order_status=20,end_time='{timer.get_now()}' where id={order['id']}"
                            sob.update_mysql_record(sob_handle, cmd)
                    sob.sql_close(sob_handle)
                    # 平台回复
                    repheard = 'fcff'
                    redatalist = [
                        {
                            'key': key_cmd, 'value': value_cmd}, {
                            'key': key_framenumber, 'value': value_framenumber}, {
                            'key': key_mac, 'value': value_mac}, {
                            'key': '0xf', 'value': '01'}]
                    redata = ''  # bkv pack数据和
                    for data in redatalist:
                        resp = pack(data)
                        redata += resp
                    # 包长
                    replen = (len(redata) + 6) / 2
                    replen = dec2hex(replen).zfill(4)
                    # 校验和
                    cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen +redata))).zfill(2).lower()
                    repmsg = repheard + replen + redata + cksum + 'fcee'
                    prolog.info('充电结束上报 resp data:{}'.format(repmsg))
                    repsend = binascii.a2b_hex(repmsg)
                    conn.send(repsend)
                elif value_cmd == '1009':
                    # 刷卡充电
                    prolog.info('---刷卡充电----')
                    # 插孔号
                    key_pile = resp[3]['key']
                    value_pile = int(resp[3]['value'], 16) + 1
                    valuepile = resp[3]['value']
                    cardlen = resp[5]['value'][-8:]
                    value_card = str(int(low_high(cardlen), 16)).zfill(10)
                    # 平台响应刷卡信息，并下发控制命令
                    sob_handle = sob.sql_open(db_config)
                    cmd = f"select * from wxapp_pod_pile where snum='{value_mac}'"
                    pod_pile = sob.select_mysql_record(sob_handle, cmd)
                    repcode,lastrowid = shua_card_rechage(pod_pile, value_card, value_pile, value_mac,2)
                    if repcode == '01':
                        # 平台回复
                        repheard = 'fcff'
                        duration = dec2hex(720)
                        redatalist = [
                            {
                                'key': '0x1', 'value': '1007'}, {
                                'key': '0x2', 'value': value_framenumber}, {
                                'key': '0x3', 'value': value_mac}, {
                                'key': '0x8', 'value': valuepile}, {
                                'key': '0x13', 'value': '01'}, {
                                'key': '0x12', 'value': '01'}, {
                                'key': '0x47', 'value': '02'}, {
                                'key': '0x14', 'value': duration.zfill(4)}, ]
                        redata = ''  # bkv pack数据和
                        for data in redatalist:
                            resp = pack(data)
                            redata += resp
                        # 包长
                        replen = (len(redata) + 6) / 2
                        replen = dec2hex(replen).zfill(4)
                        # 校验和
                        cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen +redata))).zfill(2).lower()
                        repmsg = repheard + replen + redata + cksum + 'fcee'
                        prolog.info('刷卡充电成功。resp data:{}'.format(repmsg))
                        # try:
                        repsend = binascii.a2b_hex(repmsg)
                        conn.send(repsend)
                        # except:
                        #     cmd = f"delect from wxapp_order where id={lastrowid}"
                        #     sob.delete_mysql_record(sob_handle, cmd)
                    sob.sql_close(sob_handle)
                elif value_cmd == '100A':
                    # 刷卡充电结束上报
                    # 插孔号
                    key_pile = resp[4]['key']
                    value_pile = int(resp[4]['value'], 16) + 1
                    valuepile = resp[4]['value']
                    # 插孔状态
                    key_status = resp[5]['key']
                    value_status = resp[5]['value']
                    # 当前功率
                    key_power = resp[7]['key']
                    value_power = resp[7]['value']
                    # 当前电流
                    key_electric = resp[8]['key']
                    value_electric = int(resp[8]['value'],16)
                    sob_handle = sob.sql_open(db_config)
                    cmd = f"select * from wxapp_pod_pile where snum='{value_mac}'"
                    pod_pile = sob.select_mysql_record(sob_handle, cmd)
                    if pod_pile:
                        pod_pile = pod_pile[0]
                        cmd = f"select * from wxapp_order where snum='{pod_pile['snum']}' and portnum={value_pile} and (order_status=10 or order_status=11) and add_time>'{timer.get_now_bef_aft(hours=24,is_trans=True)}' order by add_time desc"
                        orders = sob.select_mysql_record(sob_handle, cmd)
                        if orders:
                            order = orders[0]
                            end_time = timer.get_now()
                            order['end_time'] = end_time
                            # 计算充电时间判断是否大于5分钟
                            rechargetime = (timer.time2timestamp(order['end_time']) - timer.time2timestamp(
                                order['start_time'].strftime("%Y-%m-%d %H:%M:%S"))) / 60  # 分钟
                            # 结束充电
                            over_recharge(order, rechargetime, end_time, value_status, value_power, value_electric)
                    sob.sql_close(sob_handle)
                    # 平台回复
                    repheard = 'fcff'
                    redatalist = [
                        {
                            'key': key_cmd, 'value': value_cmd}, {
                            'key': key_framenumber, 'value': value_framenumber}, {
                            'key': key_mac, 'value': value_mac}, {
                            'key': key_pile, 'value': valuepile}, {
                            'key': '0xf', 'value': '01'}]
                    redata = ''  # bkv pack数据和
                    for data in redatalist:
                        resp = pack(data)
                        redata += resp
                    # 包长
                    replen = (len(redata) + 6) / 2
                    replen = dec2hex(replen).zfill(4)
                    # 校验和
                    cksum = dec2hex(
                        uchar_checksum(
                            binascii.a2b_hex(
                                replen +
                                redata))).zfill(2).lower()
                    repmsg = repheard + replen + redata + cksum + 'fcee'
                    prolog.info('刷卡充电 resp data:{}'.format(repmsg))
                    repsend = binascii.a2b_hex(repmsg)
                    conn.send(repsend)

    else:
        prolog.error('数据错误，无效长度')


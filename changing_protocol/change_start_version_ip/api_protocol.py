import binascii
import json
import secrets

from config import db_config
from tool.bkv1 import pack
from tool.calc import dec2hex, low_high, uchar_checksum, high_low
from tool.logger import MyLogger
from tool.wf_mysql import wf_mysql_class
from tool.wf_time_new import wf_time_new
from tool.wx_sdk import tl_pay_sdk, wx_pay_sdk

prolog = MyLogger("main", level=20).logger
sob = wf_mysql_class(cursor_type=True)
timer = wf_time_new()



def api_protocol(data, conn, addr,clients):
    data = json.loads(data[0])
    counter = 0  # 记录发送到客户端的个数
    for client in clients:
        print('-----------')
        print('client',client)
        if client[1][0] == data['ip']:
            if data['token'] == 'qfevserver':
                if data['command'] == 'ev_over_recharge':
                    # 结束充电
                    if data['type'] == 1:
                        if data['pattern'] == '1':  # 智能充
                            threshold = dec2hex(int(130))
                            duration = 10
                        else:
                            threshold = '0'
                            duration = data['duration']

                        port = dec2hex(int(data['portnum']))
                        duration = dec2hex(int(duration))

                        onlytag = secrets.token_hex(4)
                        servertag = '0'.zfill(8)
                        repheard = 'dddd'
                        repcheck = '0'.zfill(4)
                        # 指令数据
                        repcmd = '08'
                        # 指令 0x01 继电器闭合 0x02 继电器断开
                        port = port.zfill(2)
                        cmd = '02'
                        pattern = data['pattern'].zfill(2)
                        redata = onlytag[:4] + port + cmd + pattern + low_high(
                            duration.zfill(4)) + low_high(threshold.zfill(4))
                        replen = (len(redata) + 28) / 2
                        replen = dec2hex(replen).zfill(2)
                        repmsg = repheard + repcheck + replen + repcmd + onlytag + servertag + redata
                        prolog.info('新网结束充电 resp data:{}'.format(repmsg))
                        repsend = binascii.a2b_hex(repmsg)
                        client[0].send(repsend)
                    elif data['type'] == 2 or data['type'] == 4:
                        # 柏莱两口
                        if data['pattern'] == '1':  # 智能充
                            duration = dec2hex(int(720))
                        else:
                            duration = dec2hex(int(data['duration']))

                        port = dec2hex(int(data['portnum']))
                        pile = dec2hex(int(data['serialnum']))

                        framenumber = secrets.token_hex(4)  # 帧流水号
                        repheard = 'fcff'
                        repcmd = '07'
                        redata = '0015' + framenumber + '00' + data['onlytag'] + '8'.zfill(
                            4) + repcmd + pile.zfill(2) + \
                                 port.zfill(2) + '0'.zfill(2) + '01' + duration.zfill(4) + '0'.zfill(4)

                        replen = (len(redata) + 6) / 2
                        replen = dec2hex(replen).zfill(4)
                        cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen + redata))).zfill(2).lower()

                        repmsg = repheard + replen + redata + cksum + 'fcee'
                        prolog.info('柏来两口结束充电 resp data:{}'.format(repmsg))
                        repsend = binascii.a2b_hex(repmsg)
                        client[0].send(repsend)
                    else:
                        # 柏莱十二口
                        porthex = dec2hex(int(data['portnum']) - 1)

                        if data['pattern'] == '1':  # 智能充
                            durationhex = dec2hex(int(720))
                        else:
                            durationhex = dec2hex(int(data['duration']))
                        # 平台下发
                        framenumber = secrets.token_hex(8)  # 帧流水号
                        repheard = 'fcff'
                        redatalist = [
                            {
                                'key': '0x1', 'value': '1007'}, {
                                'key': '0x2', 'value': framenumber}, {
                                'key': '0x3', 'value': data['snum']}, {
                                'key': '0x8', 'value': porthex.zfill(2)}, {
                                'key': '0x13', 'value': '0'.zfill(2)}, {
                                'key': '0x12', 'value': '01'}, {
                                'key': '0x47', 'value': '01'}, {
                                'key': '0x14', 'value': durationhex.zfill(4)}, ]
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
                        prolog.info('柏来十二口结束充电 resp data:{}'.format(repmsg))
                        repsend = binascii.a2b_hex(repmsg)
                        client[0].send(repsend)
                    conn.send(
                        '{"status": 200, "data": "结束充电"}'.encode('utf-8'))
                    return
                elif data['command'] == 'delete_pile':
                    # 删除两孔充电桩
                    sob_handle = sob.sql_open(db_config)
                    id = data['id']
                    cmd = f"select * from wxapp_pod_pile where id={id}"
                    pod_pile = sob.select_mysql_record(sob_handle,cmd)
                    pod_pile = pod_pile[0]
                    framenumber = secrets.token_hex(4)  # 帧流水号
                    repheard = 'fcff'
                    repcmd = '0a'
                    redata = '0005' + framenumber + '00' + pod_pile['gateway_id'].zfill(14) + '7'.zfill(4) + repcmd + dec2hex(
                        int(pod_pile['serialnum'])).zfill(2) + pod_pile['snum'].zfill(12)
                    replen = (len(redata) + 6) / 2
                    replen = dec2hex(replen).zfill(4)
                    cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen +redata))).zfill(2).lower()
                    repmsg = repheard + replen + redata + cksum + 'fcee'
                    prolog.info('删除两孔充电桩 resp data:{}'.format(repmsg))

                    repsend = binascii.a2b_hex(repmsg)
                    client[0].send(repsend)
                    cmd = f"delete from wxapp_pod_pileport where pile_id={id}"
                    sob.delete_mysql_record(sob_handle,cmd)
                    cmd = f"delete from wxapp_pod_pile where id={id}"
                    sob.delete_mysql_record(sob_handle,cmd)
                    sob.sql_close(sob_handle)
                    conn.send('{"status":200,"msg":"删除成功."}'.encode('utf-8'))
                    return
                elif data['command'] == 'delete_batch_pile':
                    # 批量解绑两孔充电桩
                    sob_handle = sob.sql_open(db_config)
                    note_id = data['note_id']
                    cmd = f"select * from wxapp_pod_pile where note_id={note_id} and (type=2 or type=4)"
                    pod_piles = sob.select_mysql_record(sob_handle,cmd)
                    for pile in pod_piles:
                        framenumber = secrets.token_hex(4)  # 帧流水号
                        repheard = 'fcff'
                        repcmd = '0a'
                        redata = '0005' + framenumber + '00' + pile['gateway_id'].zfill(14) + '7'.zfill(4) + repcmd + dec2hex(
                            int(pile['serialnum'])).zfill(2) + pile['snum'].zfill(12)
                        replen = (len(redata) + 6) / 2
                        replen = dec2hex(replen).zfill(4)
                        cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen + redata))).zfill(2).lower()
                        repmsg = repheard + replen + redata + cksum + 'fcee'
                        prolog.info('删除两孔充电桩 resp data:{}'.format(repmsg))
                        repsend = binascii.a2b_hex(repmsg)
                        client[0].send(repsend)
                        cmd = f"delete from wxapp_pod_pileport where pile_id={pile['id']}"
                        sob.delete_mysql_record(sob_handle, cmd)
                        cmd = f"delete from wxapp_pod_pile where id={pile['id']}"
                        sob.delete_mysql_record(sob_handle, cmd)
                    sob.sql_close(sob_handle)
                    conn.send(
                        '{"status":200,"msg":"批量解绑成功."}'.encode('utf-8'))
                    return
                elif data['command'] == 'refresh_pile':
                    # 组网
                    onlytag = data['onlytag']
                    sob_handle = sob.sql_open(db_config)
                    cmd = f"select * from wxapp_pod_pile where gateway_id='{onlytag}' and type!=5"
                    pod_pile = sob.select_mysql_record(sob_handle, cmd)
                    pilelist = []
                    for piles in pod_pile:
                        da = {}
                        da['pile'] = piles['serialnum']
                        da['mac'] = piles['snum']
                        pilelist.append(da)

                    # 帧长
                    frame_size = dec2hex((len(pilelist) * 14 + 2) / 2).zfill(2).lower()
                    piledata = ''
                    # 刷新
                    for pile in pilelist:
                        piledata += dec2hex(int(pile['pile'])).zfill(2)
                        piledata += pile['mac'].zfill(12)
                    framenumber = secrets.token_hex(4)  # 帧流水号
                    repheard = 'fcff'
                    repcmd = '08'
                    redata = '0005' + framenumber + '00' + onlytag.zfill(14) + frame_size.zfill(
                        4) + repcmd + '04'.zfill(2) + piledata
                    replen = (len(redata) + 6) / 2
                    replen = dec2hex(replen).zfill(4)
                    cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen + redata))).zfill(2).lower()
                    repmsg = repheard + replen + redata + cksum + 'fcee'
                    prolog.info('组网 resp data:{}'.format(repmsg))
                    repsend = binascii.a2b_hex(repmsg)
                    client[0].send(repsend)
                    conn.send(
                        '{"status":200,"msg":"组网成功."}'.encode('utf-8'))
                    return
                elif data['command'] == 'payback_recharge':
                    print('支付回调充电------------')
                    '''支付回调充电'''
                    sob_handle = sob.sql_open(db_config)
                    cmd = f"select * from wxapp_pod_pile where id={data['pile_id']}"
                    pod_pile = sob.select_mysql_record(sob_handle, cmd)
                    pod_pile = pod_pile[0]
                    if pod_pile['type'] == 1:
                        # 新网-充电桩端口控制指令
                        if data['pattern'] == '1':  # 智能充
                            threshold = dec2hex(int(130))
                            duration = 10
                        else:
                            threshold = '0'
                            duration = data['duration']
                        port = dec2hex(int(data['portnum']))
                        duration = dec2hex(int(duration))
                        onlytag = secrets.token_hex(4)
                        servertag = '0'.zfill(8)
                        repheard = 'dddd'
                        repcheck = '0'.zfill(4)
                        # 指令数据
                        repcmd = '08'
                        # 指令 0x01 继电器闭合 0x02 继电器断开
                        port = port.zfill(2)
                        cmd = data['cmd'].zfill(2)
                        pattern = data['pattern'].zfill(2)
                        redata = onlytag[:4] + port + cmd + pattern + low_high(
                            duration.zfill(4)) + low_high(threshold.zfill(4))
                        replen = (len(redata) + 28) / 2
                        replen = dec2hex(replen).zfill(2)
                        repmsg = repheard + repcheck + replen + repcmd + onlytag + servertag + redata
                        prolog.info('新网充电 resp data:{}'.format(repmsg))
                        repsend = binascii.a2b_hex(repmsg)
                        client[0].send(repsend)
                        cmd = f"update wxapp_order set onlytag='{onlytag[:4]}' where id={data['order_id']}"
                        sob.update_mysql_record(sob_handle,cmd)
                    elif pod_pile['type'] == 2 or pod_pile['type'] == 4:
                        # 柏莱两口
                        if data['pattern'] == '1':  # 智能充
                            duration = dec2hex(int(720))
                        else:
                            duration = dec2hex(int(data['duration']))

                        port = dec2hex(int(data['portnum']))
                        pile = dec2hex(int(pod_pile['serialnum']))

                        framenumber = secrets.token_hex(4)  # 帧流水号
                        repheard = 'fcff'
                        repcmd = '07'
                        redata = '0015' + framenumber + '00' + pod_pile['gateway_id'] + '8'.zfill(
                            4) + repcmd + pile.zfill(2) + \
                                 port.zfill(2) + data['cmd'].zfill(2) + '01' + duration.zfill(4) + '0'.zfill(4)

                        replen = (len(redata) + 6) / 2
                        replen = dec2hex(replen).zfill(4)
                        cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen +redata))).zfill(2).lower()
                        repmsg = repheard + replen + redata + cksum + 'fcee'
                        prolog.info('柏来两口充电 resp data:{}'.format(repmsg))
                        repsend = binascii.a2b_hex(repmsg)
                        client[0].send(repsend)
                        cmd = f"update wxapp_order set onlytag='{pod_pile['gateway_id']}' where id={data['order_id']}"
                        sob.update_mysql_record(sob_handle, cmd)
                    else:
                        # 柏莱十二口
                        porthex = dec2hex(int(data['portnum']) - 1)

                        if data['pattern'] == '1':  # 智能充
                            durationhex = dec2hex(int(720))
                        else:
                            durationhex = dec2hex(int(data['duration']))

                        # 平台下发
                        framenumber = secrets.token_hex(8)  # 帧流水号
                        repheard = 'fcff'
                        redatalist = [
                            {
                                'key': '0x1', 'value': '1007'}, {
                                'key': '0x2', 'value': framenumber}, {
                                'key': '0x3', 'value': pod_pile['snum']}, {
                                'key': '0x8', 'value': porthex.zfill(2)}, {
                                'key': '0x13', 'value': data['cmd'].zfill(2)}, {
                                'key': '0x12', 'value': '01'}, {
                                'key': '0x47', 'value': '01'}, {
                                'key': '0x14', 'value': durationhex.zfill(4)}, ]
                        redata = ''  # bkv pack数据和
                        for da in redatalist:
                            resp = pack(da)
                            redata += resp
                        # 包长
                        replen = (len(redata) + 6) / 2
                        replen = dec2hex(replen).zfill(4)
                        # 校验和
                        cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen +redata))).zfill(2).lower()
                        repmsg = repheard + replen + redata + cksum + 'fcee'
                        prolog.info('柏来十二口充电 resp data:{}'.format(repmsg))
                        repsend = binascii.a2b_hex(repmsg)
                        client[0].send(repsend)
                        print(data)
                        cmd = f"update wxapp_order set onlytag='{pod_pile['snum']}' where id={data['order_id']}"
                        sob.update_mysql_record(sob_handle, cmd)
                    sob.sql_close(sob_handle)
                    conn.send('{"status": 200, "msg": "充电成功"}'.encode('utf-8'))
                    return
                elif data['command'] == 'payback_door':
                    # 门禁回调/门禁扫码/欠费付款
                    serialnum = data['serialnum']
                    doorindex = data['doorindex']

                    repheard = '17'
                    repcmd = '40' + '0'.zfill(4)
                    repdata = '0'.zfill(128)

                    idevsnhex = dec2hex(serialnum).zfill(8)
                    idevsnhex = high_low(idevsnhex)
                    prolog.info('idevsnhex:{}'.format(idevsnhex))

                    redata = repheard + repcmd + idevsnhex + doorindex + repdata
                    repmsg = redata[0:128]
                    prolog.info('开门 resp data:{}'.format(repmsg))
                    repsend = binascii.a2b_hex(repmsg)
                    client[0].send(repsend)
                    conn.send('{"status": 200, "msg": "开门成功"}'.encode('utf-8'))
                    return
                elif data['command'] == 'recharge':
                    '''充电'''
                    if data['type'] == 1:
                        # 新网-充电桩端口控制指令
                        if data['pattern'] == '1':  # 智能充
                            threshold = dec2hex(int(130))
                            duration = 10
                        else:
                            threshold = '0'
                            duration = data['duration']

                        port = dec2hex(int(data['portnum']))
                        duration = dec2hex(int(duration))

                        onlytag = secrets.token_hex(4)
                        servertag = '0'.zfill(8)
                        repheard = 'dddd'
                        repcheck = '0'.zfill(4)
                        # 指令数据
                        repcmd = '08'
                        # 指令 0x01 继电器闭合 0x02 继电器断开
                        port = port.zfill(2)
                        pattern = data['pattern'].zfill(2)
                        redata = onlytag[:4] + port + '01' + pattern + low_high(
                            duration.zfill(4)) + low_high(threshold.zfill(4))
                        replen = (len(redata) + 28) / 2
                        replen = dec2hex(replen).zfill(2)
                        repmsg = repheard + repcheck + replen + repcmd + onlytag + servertag + redata
                        prolog.info('新网充电 resp data:{}'.format(repmsg))
                        repsend = binascii.a2b_hex(repmsg)
                        client[0].send(repsend)
                    elif data['type'] == 2 or data['type'] == 4:
                        # 柏莱两口
                        if data['pattern'] == '1':  # 智能充
                            duration = dec2hex(int(720))
                        else:
                            duration = dec2hex(int(data['duration']))

                        port = dec2hex(int(data['portnum']))
                        pile = dec2hex(int(data['serialnum']))

                        framenumber = secrets.token_hex(4)  # 帧流水号
                        repheard = 'fcff'
                        repcmd = '07'
                        redata = '0015' + framenumber + '00' + data['onlytag'] + '8'.zfill(
                            4) + repcmd + pile.zfill(2) + \
                                 port.zfill(2) + '01'.zfill(2) + '01' + duration.zfill(
                            4) + '0'.zfill(4)

                        replen = (len(redata) + 6) / 2
                        replen = dec2hex(replen).zfill(4)
                        cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen + redata))).zfill(2).lower()
                        repmsg = repheard + replen + redata + cksum + 'fcee'
                        prolog.info('柏来两口充电 resp data:{}'.format(repmsg))
                        repsend = binascii.a2b_hex(repmsg)
                        client[0].send(repsend)

                    else:
                        # 柏莱十二口
                        porthex = dec2hex(int(data['portnum']) - 1)

                        if data['pattern'] == '1':  # 智能充
                            durationhex = dec2hex(int(720))
                        else:
                            durationhex = dec2hex(int(data['duration']))

                        # 平台下发
                        framenumber = secrets.token_hex(8)  # 帧流水号
                        repheard = 'fcff'
                        redatalist = [
                            {
                                'key': '0x1', 'value': '1007'}, {
                                'key': '0x2', 'value': framenumber}, {
                                'key': '0x3', 'value': data['snum']}, {
                                'key': '0x8', 'value': porthex.zfill(2)}, {
                                'key': '0x13', 'value': '01'}, {
                                'key': '0x12', 'value': '01'}, {
                                'key': '0x47', 'value': '01'}, {
                                'key': '0x14', 'value': durationhex.zfill(4)}, ]
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
                        prolog.info('柏来十二口充电 resp data:{}'.format(repmsg))
                        repsend = binascii.a2b_hex(repmsg)
                        client[0].send(repsend)

                    conn.send('{"status": 200, "data": "充电成功."}'.encode('utf-8'))
                    return
                elif data['command'] == 'upgrade':
                    '''升级'''
                    repmsg = data['repmsg']
                    repsend = binascii.a2b_hex(repmsg)
                    client[0].send(repsend)
                    conn.send('{"status":200,"msg":"升级成功."}'.encode('utf-8'))
                    return
                elif data['command'] == 'restart':
                    # 充电桩重启-重启后连接工作平台
                    onlytag = secrets.token_hex(4)
                    servertag = '0'.zfill(8)
                    repheard = 'dddd'
                    repcheck = '0'.zfill(4)
                    repcmd = '00'
                    # 指令数据
                    redata = '01'
                    replen = (len(redata) + 28) / 2
                    replen = dec2hex(replen).zfill(2)
                    repmsg = repheard + repcheck + replen + repcmd + onlytag + servertag + redata
                    prolog.info('resp data:{}'.format(repmsg))
                    repsend = binascii.a2b_hex(repmsg)
                    client[0].send(repsend)
                    conn.send('{"status":200,"msg":"重启成功."}'.encode('utf-8'))
                    return
                elif data['command'] == 'add_pile':
                    # 添加柏莱两孔充电桩
                    note_id = data['note_id']
                    mini_id = data['mini_id']
                    types = data['type']
                    pilelist = data['pilelist']
                    onlytag = data['onlytag']
                    sob_handle = sob.sql_open(db_config)
                    for pile in pilelist:
                        # #添加单个插座
                        cmd = f"select * from wxapp_pod_pile where snum='{pile['mac']}'"
                        pod_pile = sob.select_mysql_record(sob_handle, cmd)
                        if not pod_pile:
                            framenumber = secrets.token_hex(4)  # 帧流水号
                            repheard = 'fcff'
                            repcmd = '09'
                            redata = '0005' + framenumber + '00' + onlytag.zfill(14) + '7'.zfill(
                                4) + repcmd + dec2hex(int(pile['pile'])).zfill(2) + pile['mac'].zfill(12)
                            replen = (len(redata) + 6) / 2
                            replen = dec2hex(replen).zfill(4)
                            cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen + redata))).zfill(2).lower()
                            repmsg = repheard + replen + redata + cksum + 'fcee'
                            prolog.info('添加柏莱两孔充电桩 resp data:{}'.format(repmsg))
                            repsend = binascii.a2b_hex(repmsg)
                            client[0].send(repsend)
                            value_info = {
                                'serialnum':pile['pile'],
                                'gateway_id':onlytag,
                                'type':types,
                                'pileport':2,
                                'snum':pile['mac'],
                                'mini_id':mini_id,
                                'note_id':note_id,
                                'isonline':1
                            }
                            sob.insert_Or_update_mysql_record_many_new(sob_handle,'wxapp_pod_pile',[value_info])
                    sob.sql_close(sob_handle)

                    conn.send('{"status": 200, "msg": "创建成功."}'.encode('utf-8'))
                    return
                elif data['command'] == 'set_pile_param':
                    '''系统参数设置'''
                    id = data['id']
                    null_charge_power = data.get('null_charge_power')
                    null_charge_delay = data.get('null_charge_delay')
                    full_charge_power = data.get('full_charge_power')
                    full_charge_delay = data.get('full_charge_delay')
                    high_temperature = data.get('high_temperature')
                    max_recharge_time = data.get('max_recharge_time')  # 最大充电时间
                    trickle_threshold = data.get('trickle_threshold')  # 涓流阈值
                    threshold_p = data.get('threshold_p')  # 功率限值
                    threshold_i = data.get('threshold_i')  # 过流限值
                    sob_handle = sob.sql_open(db_config)
                    cmd = f"select * from wxapp_pod_pile where id={id}"
                    pod_pile = sob.select_mysql_record(sob_handle, cmd)
                    pod_pile = pod_pile[0]
                    if pod_pile['type'] == 2 or pod_pile['type'] == 4:
                        framenumber = secrets.token_hex(4)  # 帧流水号
                        repheard = 'fcff'
                        repcmd = '03'
                        redata = '0005' + framenumber + '00' + pod_pile['gateway_id'].zfill(14) + 'B'.zfill(
                            4) + repcmd + dec2hex(
                            int(pod_pile['serialnum'])).zfill(2) + '00' + dec2hex(full_charge_delay).zfill(4) + dec2hex(
                            null_charge_delay).zfill(4) + \
                                 dec2hex(int(full_charge_power * 10)).zfill(4) + dec2hex(
                            int(null_charge_power * 10)).zfill(4) + dec2hex(high_temperature).zfill(2)
                        replen = (len(redata) + 6) / 2
                        replen = dec2hex(replen).zfill(4)  # 包长
                        cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen + redata))).zfill(2).lower()  # 校验和

                        repmsg = repheard + replen + redata + cksum + 'fcee'
                        prolog.info('插座系统参数设置 resp data:{}'.format(repmsg))
                        repsend = binascii.a2b_hex(repmsg)
                        client[0].send(repsend)
                    elif pod_pile['type'] == 3:
                        # 平台下发
                        framenumber = secrets.token_hex(8)  # 帧流水号
                        repheard = 'fcff'
                        redatalist = [
                            {'key': '0x1', 'value': '100b'},
                            {'key': '0x2', 'value': framenumber},
                            {'key': '0x3', 'value': pod_pile['snum']},
                            {'key': '0x1e', 'value': dec2hex(60).zfill(4)},
                            {'key': '0x20', 'value': dec2hex(60).zfill(4)},
                            {'key': '0x21', 'value': dec2hex(full_charge_delay).zfill(4)},
                            {'key': '0x22', 'value': dec2hex(null_charge_delay).zfill(4)},
                            {'key': '0x23', 'value': dec2hex(full_charge_power * 10).zfill(4)},
                            {'key': '0x24', 'value': dec2hex(null_charge_power * 10).zfill(4)},
                            {'key': '0x25', 'value': dec2hex(high_temperature).zfill(2)},
                            {'key': '0x59', 'value': dec2hex(max_recharge_time).zfill(4)},
                            {'key': '0x60', 'value': dec2hex(trickle_threshold).zfill(2)},
                            {'key': '0x10', 'value': dec2hex(threshold_i).zfill(4)},
                            {'key': '0x11', 'value': dec2hex(threshold_p * 10).zfill(4)},
                        ]
                        redata = ''  # bkv pack数据和
                        for data in redatalist:
                            resp = pack(data)
                            redata += resp
                        # 包长
                        replen = (len(redata) + 6) / 2
                        replen = dec2hex(replen).zfill(4)
                        # 校验和
                        cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen + redata))).zfill(2).lower()
                        repmsg = repheard + replen + redata + cksum + 'fcee'
                        prolog.info('系统参数设置 resp data:{}'.format(repmsg))
                        repsend = binascii.a2b_hex(repmsg)
                        client[0].send(repsend)
                    cmd = f"select * from wxapp_default_param where pile_id={id}"
                    pod_default_param = sob.select_mysql_record(sob_handle,cmd)
                    value_info = {
                        'pile_id':id,
                        'null_charge_power':null_charge_power,
                        'null_charge_delay':null_charge_delay,
                        'full_charge_power':full_charge_power,
                        'full_charge_delay':full_charge_delay,
                        'high_temperature':high_temperature,
                    }
                    if pod_pile['type'] ==3:
                        value_info.update({
                            'max_recharge_time':max_recharge_time,
                            'trickle_threshold':trickle_threshold,
                            'threshold_p':threshold_p,
                            'threshold_i':threshold_i,
                        })
                    hope_value = list(value_info.keys())
                    if pod_default_param:
                        value_info.update({'id':pod_default_param[0]['id']})

                    sob.insert_Or_update_mysql_record_many_new(sob_handle,'wxapp_default_param',[value_info],hope_value)
                    sob.sql_close(sob_handle)
                    conn.send('{"status": 200, "msg": "设置成功."}'.encode('utf-8'))
                    return
                elif data['command'] == 'set_pile_max_elec':
                    '''设置插座最大充电电流/功率'''
                    id = data['id']
                    pilepore = data['pilepore']
                    max_elec = data['max_elec']  # 最大充电电流
                    max_power = data['max_power']  # 最大充电功率
                    sob_handle = sob.sql_open(db_config)
                    cmd = f"select * from wxapp_pod_pile where id={id}"
                    pod_pile = sob.select_mysql_record(sob_handle, cmd)
                    pod_pile = pod_pile[0]
                    if pod_pile['type'] == 2 or pod_pile['type'] == 4:
                        framenumber = secrets.token_hex(4)  # 帧流水号
                        repheard = 'fcff'
                        repcmd = '06'
                        redata = '0005' + framenumber + '00' + pod_pile['gateway_id'].zfill(14) + '6'.zfill(
                            4) + repcmd + dec2hex(int(pod_pile['serialnum'])).zfill(2) + dec2hex(pilepore).zfill(2) + \
                                 dec2hex(max_elec).zfill(4) + dec2hex(max_power).zfill(4)
                        replen = (len(redata) + 6) / 2
                        replen = dec2hex(replen).zfill(4)  # 包长
                        cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen + redata))).zfill(2).lower()  # 校验和

                        repmsg = repheard + replen + redata + cksum + 'fcee'
                        prolog.info('设置插座最大充电电流/功率 resp data:{}'.format(repmsg))
                        repsend = binascii.a2b_hex(repmsg)
                        client[0].send(repsend)
                    elif pod_pile['type'] == 3:
                        # 平台下发
                        porthex = dec2hex(pilepore - 1)
                        framenumber = secrets.token_hex(8)  # 帧流水号
                        repheard = 'fcff'
                        redatalist = [
                            {'key': '0x1', 'value': '100b'},
                            {'key': '0x2', 'value': framenumber},
                            {'key': '0x3', 'value': data['snum']},
                            {'key': '0x8', 'value': porthex.zfill(2)},
                            {'key': '0x10', 'value': dec2hex(max_elec).zfill(4)},
                            {'key': '0x11', 'value': dec2hex(max_power * 10).zfill(4)}
                        ]
                        redata = ''  # bkv pack数据和
                        for data in redatalist:
                            resp = pack(data)
                            redata += resp
                        # 包长
                        replen = (len(redata) + 6) / 2
                        replen = dec2hex(replen).zfill(4)
                        # 校验和
                        cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen + redata))).zfill(2).lower()
                        repmsg = repheard + replen + redata + cksum + 'fcee'
                        prolog.info('设置过载阈值 resp data:{}'.format(repmsg))
                        repsend = binascii.a2b_hex(repmsg)
                        client[0].send(repsend)
                    sob.sql_close(sob_handle)
                    conn.send('{"status": 200, "msg": "设置成功."}'.encode('utf-8'))
                    return
                elif data['command'] == 'get_pile_param':
                    '''查询插座参数'''
                    id = data['id']
                    sob_handle = sob.sql_open(db_config)
                    cmd = f"select * from wxapp_pod_pile where id={id}"
                    pod_pile = sob.select_mysql_record(sob_handle, cmd)
                    pod_pile = pod_pile[0]
                    if pod_pile['type'] == 2 or pod_pile['type'] == 4:
                        framenumber = secrets.token_hex(4)  # 帧流水号
                        repheard = 'fcff'
                        repcmd = '13'
                        redata = '0005' + framenumber + '00' + pod_pile['gateway_id'].zfill(14) + '1'.zfill(
                            4) + repcmd + dec2hex(
                            int(pod_pile['serialnum'])).zfill(2)
                        replen = (len(redata) + 6) / 2
                        replen = dec2hex(replen).zfill(4)  # 包长
                        cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen + redata))).zfill(2).lower()  # 校验和
                        repmsg = repheard + replen + redata + cksum + 'fcee'
                        prolog.info('插座系统参数获取 resp data:{}'.format(repmsg))
                        repsend = binascii.a2b_hex(repmsg)
                        client[0].send(repsend)
                    elif pod_pile['type'] == 3:
                        # 平台下发
                        framenumber = secrets.token_hex(8)  # 帧流水号
                        repheard = 'fcff'
                        redatalist = [
                            {'key': '0x1', 'value': '100c'},
                            {'key': '0x2', 'value': framenumber},
                            {'key': '0x3', 'value': pod_pile['snum']},
                        ]
                        redata = ''  # bkv pack数据和
                        for data in redatalist:
                            resp = pack(data)
                            redata += resp
                        # 包长
                        replen = (len(redata) + 6) / 2
                        replen = dec2hex(replen).zfill(4)
                        # 校验和
                        cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen + redata))).zfill(2).lower()
                        repmsg = repheard + replen + redata + cksum + 'fcee'
                        prolog.info('系统参数查询 resp data:{}'.format(repmsg))
                        repsend = binascii.a2b_hex(repmsg)
                        client[0].send(repsend)
                    conn.send('{"status": 200, "msg": "获取成功."}'.encode('utf-8'))
                    return
                elif data['command'] == 'ota_upgrade':
                    '''ota升级'''
                    # 平台下发
                    framenumber = secrets.token_hex(8)  # 帧流水号
                    repheard = 'fcff'
                    redatalist = [
                        {'key': '0x1', 'value': '1008'},
                        {'key': '0x2', 'value': framenumber},
                        {'key': '0x3', 'value': data['snum']},
                        {'key': '0x19', 'value': '00000000000000000000FFFF784EAEA2'},  # ipv6十六进制120.78.174.162
                        {'key': '0x1a', 'value': '15'.zfill(4)},
                        {'key': '0x1b', 'value': '7a782e31387232372e4f5441'},  # zx.18r27.OTA/129.204.99.125:47881
                    ]
                    redata = ''  # bkv pack数据和
                    for data in redatalist:
                        resp = pack(data)
                        redata += resp
                    # 包长
                    replen = (len(redata) + 6) / 2
                    replen = dec2hex(replen).zfill(4)
                    # 校验和
                    cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen + redata))).zfill(2).lower()
                    repmsg = repheard + replen + redata + cksum + 'fcee'
                    prolog.info('ota升级 resp data:{}'.format(repmsg))
                    repsend = binascii.a2b_hex(repmsg)
                    client[0].send(repsend)
                    conn.send('{"status":200,"msg":"升级成功."}'.encode('utf-8'))
                    return
            else:
                conn.send('{"status":400,"data":"token验证失败."}'.encode('utf-8'))
                return
            counter += 1
    if counter == 0:
        conn.send('{"status": 400, "data": "无效ip."}'.encode('utf-8'))
        return
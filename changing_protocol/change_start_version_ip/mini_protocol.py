import binascii
import json
import secrets

from change_start_version_ip.normal_query import get_setting
from config import db_config, REQ_HOST
from tool.bkv1 import pack
from tool.calc import dec2hex, low_high, uchar_checksum
from tool.logger import MyLogger
from tool.wf_mysql import wf_mysql_class
from tool.wf_time_new import wf_time_new
from tool.wx_sdk import tl_pay_sdk, wx_pay_sdk

prolog = MyLogger("main", level=20).logger
sob = wf_mysql_class(cursor_type=True)
timer = wf_time_new()


def mini_protocol(data, conn, addr,clients):
    data = json.loads(data[0])
    counter = 0  # 记录发送到客户端的个数
    for client in clients:
        if client[1][0] == data['ip']:
            if data['token'] == 'qfevserver':
                if data['command'] == 'recharge':
                    sob_handle = sob.sql_open(db_config)
                    # 查看是否有充电中的订单
                    cmd = f"select * from wxapp_order where user_id={data['user_id']} and (order_status=10 or order_status=1)"
                    orders = sob.select_mysql_record(sob_handle, cmd)
                    if orders:
                        conn.send(str({'msg': '您有一笔订单正在进行中', 'data': orders[0]['id'], 'status': 206}).encode('utf-8'))
                        return
                    # 查看是否有已完成未支付的订单
                    cmd = f"select * from wxapp_order where user_id={data['user_id']} and pay_status=10 and (order_status=11 or order_status=20) and pay_price!=0"
                    pay_orders = sob.select_mysql_record(sob_handle, cmd)
                    if pay_orders:
                        conn.send(str({'msg': '您有一笔订单未支付', 'data': pay_orders[0]['id'], 'status': 205}).encode('utf-8'))
                        return
                    # 端口是否被占用
                    cmd = f"select * from wxapp_order where pile_id={data['pile_id']} and portnum='{data['portnum']}' and order_status=10"
                    order_pileport = sob.select_mysql_record(sob_handle, cmd)
                    if order_pileport:
                        conn.send(str({'msg': '端口被占用，请选择其他端口充电', 'status': 400}).encode('utf-8'))
                        return
                    cmd = f"select * from wxapp_user where id={data['user_id']} "
                    user = sob.select_mysql_record(sob_handle, cmd)
                    if user:
                        user = user[0]
                        if user['is_freeze'] == 1:
                            conn.send(str({'msg': '账户已被冻结。', 'status': 400}).encode('utf-8'))
                            return
                    bill_id = data['bill_id']
                    is_charge_buy = int(data['is_charge_buy'])
                    cmd = f"select * from wxapp_bill where id={bill_id}"
                    bills = sob.select_mysql_record(sob_handle,cmd)
                    bill = bills[0]
                    cmd = f"select * from wxapp_note where id={bill['note_id']}"
                    notes = sob.select_mysql_record(sob_handle,cmd)
                    note = notes[0]
                    cmd = f"select * from wxapp_pod_pile where id={data['pile_id']}"
                    pod_piles = sob.select_mysql_record(sob_handle,cmd)
                    pod_pile = pod_piles[0]
                    cmd = f"select * from wxapp_pod_pileport where pile_id={data['pile_id']} and portnum={data['portnum']}"
                    pod_pileports = sob.select_mysql_record(sob_handle,cmd)
                    pod_pileport = pod_pileports[0]

                    price_one = 0
                    first_proportion_money = 0
                    second_proportion_money = 0
                    total_price = 0
                    pay_price = 0

                    if not user['note_id']: ##根据用户首次使用场地做用户属性归属
                        cmd = f"update wxapp_user set note_id={bill['note_id']} where id={user['id']}"
                        sob.update_mysql_record(sob_handle,cmd)

                    cmd = f"select * from wxapp_white_list where user_id={data['user_id']} and note_id={bill['note_id']} and special_end>'{timer.get_now()}' and special_start<'{timer.get_now()}' and type=2"
                    white_user = sob.select_mysql_record(sob_handle, cmd)
                    if white_user:
                        if bill['billtype'] == 0:
                            recharge_time = bill['duration']  # 小时
                        elif bill['billtype'] == 1: # 按小时
                            recharge_time = data['hours']  # 小时
                        elif bill['billtype'] == 3: # 按挡位充电
                            recharge_time = data['hours']  # 小时
                        else:
                            recharge_time = 0
                    else:
                        cmd = f"select * from wxapp_recharge_package_order where user_id={data['user_id']} and note_id={bill['note_id']} and pay_status=20 and type=2 and start_time<='{timer.get_now()}' and end_time>='{timer.get_now()}' and order_status=20 and residue_time>0"
                        recharge_package_orders = sob.select_mysql_record(sob_handle, cmd)

                        if is_charge_buy == 1:
                            values_json = get_setting(data['mini_id'],'charge')
                            price_one = float(values_json.get('price_one',0))

                        for recharge in recharge_package_orders:
                            if recharge['is_charge_buy'] == 1:
                                price_one = 0
                                is_charge_buy = 1

                        if note['is_ind_dealer'] == 1:  # 开启单独分成
                            first_proportion = note['first_proportion']
                            second_proportion = note['second_proportion']
                        else:
                            values_json = get_setting(data['mini_id'], 'settlement')
                            first_proportion = int(values_json.get('first_proportion',0))  # 一级分成比例
                            second_proportion = int(values_json.get('second_proportion',0))  # 二级分成比例

                        is_pay = False
                        if bill['billtype'] == 0:
                            recharge_time = bill['duration']  # 小时
                            end_time = timer.get_now_bef_aft(hours=-recharge_time)
                            total_price = price_one + bill['total_price']
                            for recharge in recharge_package_orders:
                                if recharge['end_time'] > end_time:  # 套餐包结束时间大于充电订单结束时间
                                    if recharge['residue_time'] >= recharge_time:
                                        cmd = f"update wxapp_recharge_package_order set residue_time=residue_time-{recharge_time} where id={recharge['id']}"
                                        sob.update_mysql_record(sob_handle, cmd)
                                        pay_price = price_one
                                        is_pay = True  # 套餐扣费
                                        break
                            if is_pay == False:  # 套餐时间不足
                                pay_price = bill['total_price'] + price_one
                                first_proportion_money = pay_price * (first_proportion / 100)
                                second_proportion_money = pay_price * (second_proportion / 100)
                        elif bill['billtype'] == 1:
                            recharge_time = int(data['hours'])  # 小时
                            end_time = timer.get_now_bef_aft(hours=-recharge_time)
                            total_price = recharge_time * bill['price'] + price_one
                            for recharge in recharge_package_orders:
                                if recharge['end_time'] > end_time:  # 套餐包结束时间大于充电订单结束时间
                                    if recharge['residue_time'] >= recharge_time:
                                        cmd = f"update wxapp_recharge_package_order set residue_time=residue_time-{recharge_time} where id={recharge['id']}"
                                        sob.update_mysql_record(sob_handle, cmd)
                                        pay_price = price_one
                                        is_pay = True  # 套餐扣费
                                        break
                            if is_pay == False:  # 套餐时间不足
                                pay_price = recharge_time * bill['price'] + price_one
                                first_proportion_money = pay_price * (first_proportion / 100)
                                second_proportion_money = pay_price * (second_proportion / 100)
                        elif bill['billtype'] == 3:
                            recharge_time = int(data['hours'])  # 时长
                            end_time = timer.get_now_bef_aft(hours=-recharge_time)
                            total_price = note['predict_price'] + price_one  # 预扣金额
                            for recharge in recharge_package_orders:
                                if recharge['end_time'] > end_time:  # 套餐包结束时间大于充电订单结束时间
                                    if recharge['residue_time'] >= recharge_time:
                                        cmd = f"update wxapp_recharge_package_order set residue_time=residue_time-{recharge_time} where id={recharge['id']}"
                                        sob.update_mysql_record(sob_handle, cmd)
                                        pay_price = price_one
                                        is_pay = True  # 套餐扣费
                                        break
                            if is_pay == False:  # 套餐时间不足
                                pay_price = note['predict_price'] + price_one  # 预扣金额
                                first_proportion_money = pay_price * (first_proportion / 100)
                                second_proportion_money = pay_price * (second_proportion / 100)
                        else: # 充满自停
                            pay_price = 0
                            end_time = 0
                            recharge_time = 0
                            if not recharge_package_orders:
                                if user['virtual_balance'] < note['predict_price']:
                                    if user['balance'] < note['predict_price']:
                                        conn.send(str({'msg': '账户余额不足，请充值。', 'status': 207}).encode('utf-8'))
                                        return

                    order_id = f"{timer.get_now(format='%Y%m%d%H%M%S')}{data['user_id']}"
                    value_info = {
                        'order_id': order_id,
                        'mini_id': user['mini_id'],
                        'note_id': note['id'],
                        'user_id': data['user_id'],
                        'pile_id': data['pile_id'],
                        'pileport_id': pod_pileport['id'],
                        'snum': pod_pile['snum'],
                        'start_time': timer.get_now(),
                        'portnum': data['portnum'],
                        'recharge_time':recharge_time,
                        'pay_price':pay_price,
                        'total_price':total_price,
                        'order_status': 1,
                        'pay_status': 10,
                        'is_charge_buy': is_charge_buy,
                        'billtype': bill['billtype'],
                        'first_proportion_money': first_proportion_money,
                        'second_proportion_money': second_proportion_money,
                        'add_time':timer.get_now()
                    }
                    lastrowid = sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_order', [value_info])
                    if pay_price:
                        if user['virtual_balance'] >= pay_price:
                            cmd = f"update wxapp_user set virtual_balance=virtual_balance-{pay_price} where id={user['id']}"
                            sob.update_mysql_record(sob_handle, cmd)
                            value_info = {
                                'mini_id': data['mini_id'],
                                'note_id': note['id'],
                                'user_id': user['id'],
                                'type': 1,
                                'start_time': timer.get_now(),
                                'scene': 21,
                                'money': pay_price,
                                'describes': '用户消费(虚拟钱包扣款)',
                                'add_time': timer.get_now()
                            }
                            sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_user_balance_log',[value_info])
                            cmd = f"update wxapp_order set pay_type=60,pay_status=20,pay_time='{timer.get_now()}' where id={lastrowid}"
                            sob.update_mysql_record(sob_handle, cmd)
                        elif user['balance'] >= pay_price:
                            cmd = f"update wxapp_user set balance=balance-{pay_price} where id={user['id']}"
                            sob.update_mysql_record(sob_handle, cmd)
                            value_info = {
                                'mini_id': data['mini_id'],
                                'note_id': note['id'],
                                'user_id': user['id'],
                                'type': 1,
                                'start_time': timer.get_now(),
                                'scene': 21,
                                'money': pay_price,
                                'describes': '用户消费(余额扣款)',
                                'add_time': timer.get_now()
                            }
                            sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_user_balance_log',[value_info])
                            cmd = f"update wxapp_order set pay_type=10,pay_status=20,pay_time='{timer.get_now()}' where id={lastrowid}"
                            sob.update_mysql_record(sob_handle, cmd)
                        else:
                            total_money = int(pay_price * 100)
                            cmd = f"select * from wxapp_payinfo where mini_id={data['mini_id']}"
                            payinfo = sob.select_mysql_record(sob_handle, cmd)
                            if payinfo:
                                payinfo = payinfo[0]
                                if payinfo['pay_type'] == 2:  # 通联支付
                                    notify_url = f'{REQ_HOST}/api/tl_order_payback'
                                    tl_pay = tl_pay_sdk()
                                    resp = tl_pay.tl_mini_pay(payinfo['apikey'],payinfo['orgid'], payinfo['mchid'],
                                                                 order_id,total_money, notify_url,
                                                                      payinfo['key_pem'])
                                    cmd = f"update wxapp_order set cmd=1,pay_type=20,pay_status=10,order_status=0 where id={lastrowid}"
                                    sob.update_mysql_record(sob_handle, cmd)
                                    conn.send(str({'data': resp, 'status': 200, 'order_id': lastrowid}).encode('utf-8'))
                                    return
                                else:
                                    cmd = f"select * from wxapp_mini where id={data['mini_id']}"
                                    wxapp_minis = sob.select_mysql_record(sob_handle,cmd)
                                    wxapp_mini = wxapp_minis[0]
                                    notify_url = f'{REQ_HOST}/api/wx_order_payback/{payinfo["orgid"]}'
                                    results, data = wx_pay_sdk().mini_pay(wxapp_mini['authorizer_appid'],payinfo['mchid'],
                                                          order_id,total_money,user['open_id'],notify_url,payinfo['apikey'],payinfo['key_pem'])
                                    if results['xml']['return_code'] == 'SUCCESS':
                                        if results['xml']['result_code'] == 'SUCCESS':
                                            cmd = f"update wxapp_order set cmd=1,pay_type=20,pay_status=10,order_status=0 where id={lastrowid}"
                                            sob.update_mysql_record(sob_handle, cmd)
                                            conn.send(str({'data': data, 'status': 200, 'order_id': lastrowid}).encode('utf-8'))
                                            return
                                        else:
                                            return_msg = results['xml']['return_msg']
                                    else:
                                        return_msg = results['xml']['return_msg']

                                    cmd = f"delete from wxapp_order where id={lastrowid}"
                                    sob.delete_mysql_record(sob_handle,cmd)
                                    conn.send(str({'return_msg': return_msg, 'status': 400}).encode('utf-8'))
                                    return
                    else:
                        if bill['billtype'] !=2 and bill['billtype'] !=2:
                            cmd = f"update wxapp_order set pay_status=20,pay_type=30,pay_time='{timer.get_now()}' where id={lastrowid}"
                            sob.update_mysql_record(sob_handle,cmd)
                        if white_user:
                            cmd = f"update wxapp_order set pay_status=20,pay_type=50,pay_time='{timer.get_now()}' where id={lastrowid}"
                            sob.update_mysql_record(sob_handle, cmd)
                    try:
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
                            prolog.info('新网充电指令 resp data:{}'.format(repmsg))
                            repsend = binascii.a2b_hex(repmsg)
                            client[0].send(repsend)
                            cmd = f"update wxapp_order set onlytag='{onlytag[:4]}' where id={lastrowid}"
                            sob.update_mysql_record(sob_handle, cmd)
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
                                     port.zfill(2) + data['cmd'].zfill(2) + '01' + duration.zfill(
                                4) + '0'.zfill(4)
                            replen = (len(redata) + 6) / 2
                            replen = dec2hex(replen).zfill(4)
                            cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen +redata))).zfill(2).lower()

                            repmsg = repheard + replen + redata + cksum + 'fcee'
                            prolog.info('柏来两口充电 resp data:{}'.format(repmsg))
                            repsend = binascii.a2b_hex(repmsg)
                            client[0].send(repsend)
                            cmd = f"update wxapp_order set onlytag='{pod_pile['gateway_id']}' where id={lastrowid}"
                            sob.update_mysql_record(sob_handle, cmd)
                        else:
                                # 柏莱十二口和十口
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
                                for data in redatalist:
                                    resp = pack(data)
                                    redata += resp
                                # 包长
                                replen = (len(redata) + 6) / 2
                                replen = dec2hex(replen).zfill(4)
                                # 校验和
                                cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen + redata))).zfill(2).lower()
                                repmsg = repheard + replen + redata + cksum + 'fcee'
                                prolog.info('柏来十二口充电 resp data:{}'.format(repmsg))
                                repsend = binascii.a2b_hex(repmsg)
                                client[0].send(repsend)
                                cmd = f"update wxapp_order set onlytag='{pod_pile['snum']}' where id={lastrowid}"
                                sob.update_mysql_record(sob_handle, cmd)

                    except:
                        cmd = f"update wxapp_pod_pileport set trouble_status=1 where id={pod_pileport['id']}"
                        sob.update_mysql_record(sob_handle,cmd)
                        cmd = f"select * from wxapp_order where id={lastrowid}"
                        orders = sob.select_mysql_record(sob_handle,cmd)
                        if pay_price:
                            if orders[0]['pay_type'] == 10:
                                cmd = f"update wxapp_user set balance=balance+{pay_price} where id={user['id']}"
                                sob.update_mysql_record(sob_handle,cmd)
                            elif orders[0]['pay_type'] == 60:
                                cmd = f"update wxapp_user set virtual_balance=virtual_balance+{pay_price} where id={user['id']}"
                                sob.update_mysql_record(sob_handle,cmd)
                        if orders[0]['pay_type'] == 30:
                            package_order = recharge_package_orders[0]
                            cmd = f"update wxapp_recharge_package_order set residue_time=residue_time+{recharge_time} where id={package_order['id']}"
                            sob.update_mysql_record(sob_handle,cmd)

                        cmd = f"delete from wxapp_order where id={lastrowid}"
                        sob.delete_mysql_record(sob_handle,cmd)
                        conn.send(str({"msg": "充电失败，请重试", "status": 400}).encode('utf-8'))
                        return

                    cmd = f"update wxapp_pod_pileport set portstatus=1 where id={pod_pileport['id']}"
                    sob.update_mysql_record(sob_handle,cmd)
                    print('充电成功。。。。。。。')
                    conn.send(str({"msg": "充电成功", "status": 200, "data": lastrowid}).encode('utf-8'))
                    sob.sql_close(sob_handle)
                    return
                elif data['command'] == 'over_recharge':
                    sob_handle = sob.sql_open(db_config)
                    end_time = timer.get_now()
                    cmd = f"select * from wxapp_order where id={data['order_id']}"
                    orders = sob.select_mysql_record(sob_handle, cmd)
                    order = orders[0]
                    cmd = f"select * from wxapp_pod_pile where id={order['pile_id']}"
                    pod_piles = sob.select_mysql_record(sob_handle,cmd)
                    pod_pile = pod_piles[0]
                    pattern = '2'
                    if order['billtype'] == 2:
                        pattern = '1'
                    if not order['recharge_time']:
                        recharge_time = (timer.time2timestamp(end_time) - timer.time2timestamp(order['start_time'].strftime("%Y-%m-%d %H:%M:%S"))) / 360
                    else:
                        recharge_time = order['recharge_time']
                    cmd = f"update wxapp_order set order_status=11,end_time='{end_time}',recharge_time={recharge_time} where id={data['order_id']}"
                    sob.update_mysql_record(sob_handle, cmd)
                    if pod_pile['type'] == 1:
                        if pattern == '1':  # 智能充
                            threshold = dec2hex(int(130))
                            duration = 10
                        else:
                            threshold = '0'
                            duration = int(recharge_time * 60)

                        port = dec2hex(int(order['portnum']))
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
                        pattern = pattern.zfill(2)
                        redata = onlytag[:4] + port + cmd + pattern + low_high(
                            duration.zfill(4)) + low_high(threshold.zfill(4))
                        replen = (len(redata) + 28) / 2
                        replen = dec2hex(replen).zfill(2)
                        repmsg = repheard + repcheck + replen + repcmd + onlytag + servertag + redata
                        prolog.info('新网结束充电 resp data:{}'.format(repmsg))
                        repsend = binascii.a2b_hex(repmsg)
                        client[0].send(repsend)
                    elif pod_pile['type'] == 2 or pod_pile['type'] == 4:
                        # 柏莱两口
                        if pattern == '1':  # 智能充
                            duration = dec2hex(int(720))
                        else:
                            duration = dec2hex(int(recharge_time * 60))

                        port = dec2hex(int(order['portnum']))
                        pile = dec2hex(int(pod_pile['serialnum']))

                        framenumber = secrets.token_hex(4)  # 帧流水号
                        repheard = 'fcff'
                        repcmd = '07'
                        redata = '0015' + framenumber + '00' + pod_pile['gateway_id'] + '8'.zfill(
                            4) + repcmd + pile.zfill(2) + \
                                 port.zfill(2) + '0'.zfill(2) + '01' + duration.zfill(4) + '0'.zfill(4)
                        replen = (len(redata) + 6) / 2
                        replen = dec2hex(replen).zfill(4)
                        cksum = dec2hex(uchar_checksum(binascii.a2b_hex(replen +redata))).zfill(2).lower()
                        repmsg = repheard + replen + redata + cksum + 'fcee'
                        prolog.info('柏来两口结束充电 resp data:{}'.format(repmsg))
                        repsend = binascii.a2b_hex(repmsg)
                        client[0].send(repsend)
                    else:
                        # 柏莱十二口
                        porthex = dec2hex(int(order['portnum']) - 1)

                        if pattern == '1':  # 智能充
                            durationhex = dec2hex(int(720))
                        else:
                            durationhex = dec2hex(int(recharge_time * 60))

                        # 平台下发
                        framenumber = secrets.token_hex(8)  # 帧流水号
                        repheard = 'fcff'
                        redatalist = [
                            {
                                'key': '0x1', 'value': '1007'}, {
                                'key': '0x2', 'value': framenumber}, {
                                'key': '0x3', 'value': pod_pile['snum']}, {
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
                    sob.sql_close(sob_handle)
                    conn.send(
                        str({"status": 200, "msg": "结束成功"}).encode('utf-8'))
                    return
                counter += 1
            else:
                conn.send(str({"status": 400, "msg": "token验证失败."}).encode('utf-8'))
                return
    if counter == 0:
        conn.send('{"status": 400, "msg": "无效ip."}'.encode('utf-8'))
        return



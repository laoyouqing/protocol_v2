import datetime
import json
import math
import os
import secrets
import sys

# sys.path.append(os.path.dirname(os.path.realpath(__file__)))
# sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
from config import db_config, REQ_HOST
from tool.logger import MyLogger
from tool.wf_mysql import wf_mysql_class
from tool.wf_time_new import wf_time_new
from tool.wx_sdk import wx_mini_sdk, tl_pay_sdk, wx_pay_sdk

prolog = MyLogger("main", level=20).logger
sob = wf_mysql_class(cursor_type=True)
timer = wf_time_new()

def get_setting(mini_id,title):
    values_json = {}
    sob_handle = sob.sql_open(db_config)
    cmd = f"select * from wxapp_setting where mini_id={mini_id} and title='{title}'"
    info = sob.select_mysql_record(sob_handle,cmd)
    sob.sql_close(sob_handle)
    if info:
        values_json = json.loads(info[0]['values_json'])
    return values_json


def start_rechage_send_tempalte(access_token,order,template_id):
    data = {
        "thing1": {
            "value": order['note_name']},
        "character_string2": {
            "value": order['snum']},
        "thing5": {
            "value": str(order['recharge_time'] * 60) + '分钟' if order['recharge_time'] * 60 else '充满自停'},
        "date11": {
            "value": order['start_time'].strftime("%Y-%m-%d %H:%M:%S")},
        "thing33": {
            "value": '充电成功，请锁好爱车并带走贵重物品'}}
    resp = wx_mini_sdk().send_tempalte_keyword(access_token, order['open_id'], template_id,
    'pages/index/children/charging?order_id={}'.format(order['id']), data)
    print('充电成功....',resp)



def get_access_token(mini_id):
    access_token = ''
    sob_handle = sob.sql_open(db_config)
    cmd = f"select * from wxapp_mini where id={mini_id}"
    info = sob.select_mysql_record(sob_handle,cmd)
    if info:
        info = info[0]
        if info['expird_time'] and info['expird_time'].strftime("%Y-%m-%d %H:%M:%S") > timer.get_now():
            access_token = info['access_token']
        else:
            re_dict = wx_mini_sdk().get_access_token(info['authorizer_appid'],info['secret'])
            access_token = re_dict['access_token']
            expird_time = timer.get_now_bef_aft(seconds=-7000,is_trans=True)
            cmd = f"update wxapp_mini set access_token='{access_token}',expird_time='{expird_time}' where id={info['id']}"
            sob.update_mysql_record(sob_handle,cmd)
    sob.sql_close(sob_handle)
    return access_token



def invalid_dealer_order(order):
    try:
        sob_handle = sob.sql_open(db_config)
        cmd = f"update wxapp_dealer_order set is_invalid=1 where order_id={order['id']}"
        sob.update_mysql_record(sob_handle,cmd)
        if order['is_settled'] == 1:# 已结算
            cmd = f"select account_id from wxapp_dealer_order where order_id={order['id']} and is_settled=1"
            dealer_orders = sob.select_mysql_record(sob_handle,cmd)
            for dealer in dealer_orders:
                cmd = f"update wxapp_dealer_note set money=money-{dealer['share_money']} where account_id={dealer['account_id']}"
                sob.update_mysql_record(sob_handle,cmd)
        sob.sql_close(sob_handle)
    except:
        prolog.error('结算回退出错')

def worry_free_price(mini_id):
    '''无忧充电单价'''
    try:
        values_json = get_setting(mini_id,'charge')
        price_one = float(values_json.get('price_one'))  # 单价
        return price_one
    except:
        return 0


def over_recharge(order,rechargetime,end_time,plugstatus,power,electric):
    # try:
        print('结束充电。。。。。')
        sob_handle = sob.sql_open(db_config)
        cmd = f"select * from wxapp_user where id={order['user_id']}"
        users = sob.select_mysql_record(sob_handle, cmd)
        user = users[0]
        if order['pay_type'] != 50:  # 不是白名单用户
            if rechargetime > 5:
                price_one = 0
                if order['is_charge_buy'] == 1: #如果购买无忧充电
                    price_one = worry_free_price(order['mini_id'])  # 无忧充电单价
                
                cmd = f"select * from wxapp_note where id={order['note_id']}"
                notes = sob.select_mysql_record(sob_handle,cmd)
                note = notes[0]
                if note['is_ind_dealer'] == 1:  # 开启单独分成
                    first_proportion = note['first_proportion']
                    second_proportion = note['second_proportion']
                else:
                    values_json = get_setting(order['mini_id'], 'settlement')
                    first_proportion = int(values_json.get('first_proportion',0))  # 一级分成比例
                    second_proportion = int(values_json.get('second_proportion',0))  # 二级分成比例
                # try:
                if note['bill_type'] == 0: #按时
                    calc_order_refund(order, note, rechargetime, first_proportion, second_proportion)
                else:
                    print('分档充电。。。。。')
                    calc_order_tranche_fefund(order, note, rechargetime, first_proportion, second_proportion)
                # except:
                #     prolog.error(f"充电时长不足退款异常:订单{order['id']}")
                if order['billtype'] == 2:# 充满自停
                    cmd = f"select * from wxapp_bill where note_id={note['id']} and billtype=2"
                    bills = sob.select_mysql_record(sob_handle,cmd)
                    if bills:
                        bill = bills[0]
                        is_ceil = bill['is_ceil']
                        step = bill['step']
                        recharge_time = (timer.time2timestamp(end_time) - timer.time2timestamp(order['start_time'].strftime("%Y-%m-%d %H:%M:%S"))) / 3600  # 小时
                        if is_ceil == 1:
                            if recharge_time < step:  # 小于步长
                                recharge_time = step
                            else:  # 大于步长
                                digit = (timer.time2timestamp(end_time) - timer.time2timestamp(order['start_time'].strftime("%Y-%m-%d %H:%M:%S"))) % 3600  # 余数
                                if digit < 300:  # 余数小于300秒（5分钟）
                                    recharge_time = int(recharge_time)  # 向下取整
                                recharge_time = math.ceil(recharge_time / step) * step
                        recharge_time_total = recharge_time
                        start_time = order['start_time'].strftime("%Y-%m-%d %H:%M:%S")
                        cmd = f"select * from wxapp_recharge_package_order where user_id={order['user_id']} and note_id={note['id']} and pay_status=20 and type=2 and end_time>='{start_time}' and order_status=20 and residue_time>0"
                        recharge_package_orders = sob.select_mysql_record(sob_handle, cmd)
                        for recharge in recharge_package_orders:
                            if recharge['is_charge_buy'] == 1:
                                price_one = 0
                        is_pay = False
                        first_proportion_money = 0
                        second_proportion_money = 0
                        total_price = 0
                        pay_price = 0
                        for recharge in recharge_package_orders:
                            if recharge['end_time'] > datetime.datetime.strptime(order['end_time'], '%Y-%m-%d %H:%M:%S'):# 套餐包结束时间大于充电订单结束时间
                                if recharge['residue_time'] >= recharge_time:
                                    cmd = f"update wxapp_recharge_package_order set residue_time=residue_time-{recharge_time} where id={recharge['id']}"
                                    sob.update_mysql_record(sob_handle,cmd)
                                    cmd = f"update wxapp_order set pay_price=0,pay_type=30,pay_status=20,pay_time='{timer.get_now()}' where id={order['id']}"
                                    sob.update_mysql_record(sob_handle,cmd)
                                    is_pay = True  # 套餐扣费
                                    break
                                else:
                                    recharge_time = recharge_time - recharge['residue_time']  # 需要扣费的时间
                                    cmd = f"update wxapp_recharge_package_order set residue_time=0 where id={recharge['id']}"
                                    sob.update_mysql_record(sob_handle, cmd)
                            else:
                                stime = (timer.time2timestamp(recharge['end_time'].strftime("%Y-%m-%d %H:%M:%S")) - timer.time2timestamp(order['start_time'].strftime("%Y-%m-%d %H:%M:%S"))) / 3600  # 到期前套餐包使用时间
                                if recharge['residue_time'] >= stime:
                                    recharge_time = (timer.time2timestamp(order['end_time'].strftime("%Y-%m-%d %H:%M:%S")) -timer.time2timestamp(recharge['end_time'].strftime("%Y-%m-%d %H:%M:%S"))) / 3600  # 需要扣费的时间
                                else:
                                    recharge_time = recharge_time - recharge['residue_time']  # 需要扣费的时间
                                    cmd = f"update wxapp_recharge_package_order set residue_time=0 where id={recharge['id']}"
                                    sob.update_mysql_record(sob_handle, cmd)
                        if is_pay == False: # 套餐时间不足
                            if is_ceil == 1:
                                if recharge_time < step:  # 小于步长
                                    recharge_time = step
                                else:  # 大于步长
                                    recharge_time = math.ceil(recharge_time / step) * step
                                total_price = bill['price'] * recharge_time + price_one
                                pay_price = bill['price'] * recharge_time + price_one
                            else:
                                total_price = bill['price'] * recharge_time*60 + price_one
                                pay_price = bill['price'] * recharge_time*60 + price_one
                            first_proportion_money = total_price * (first_proportion / 100)  # 一级（代理商）分成
                            second_proportion_money = total_price * (second_proportion / 100)  # 二级（物业）分成
                            if user['virtual_balance'] >= pay_price:
                                cmd = f"update wxapp_user set virtual_balance=virtual_balance-{pay_price} where id={order['user_id']}"
                                sob.update_mysql_record(sob_handle, cmd)
                                value_info = {
                                    'mini_id': order['mini_id'],
                                    'note_id': order['note_id'],
                                    'type': 1,
                                    'start_time': str(order['start_time']),
                                    'end_time': str(order['end_time']),
                                    'user_id': order['user_id'],
                                    'scene': 21,
                                    'money': pay_price,
                                    'describes': '用户消费(虚拟钱包扣款)',
                                    'add_time': timer.get_now()
                                }
                                sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_user_balance_log',[value_info])
                                cmd = f"update wxapp_order set pay_type=60,pay_status=20,pay_time='{timer.get_now()}' where id={order['id']}"
                                sob.update_mysql_record(sob_handle, cmd)
                            elif user['balance'] >= pay_price:
                                cmd = f"update wxapp_user set balance=balance-{pay_price} where id={order['user_id']}"
                                sob.update_mysql_record(sob_handle, cmd)
                                value_info = {
                                    'mini_id': order['mini_id'],
                                    'note_id': order['note_id'],
                                    'type': 1,
                                    'start_time': str(order['start_time']),
                                    'end_time': str(order['end_time']),
                                    'user_id': order['user_id'],
                                    'scene': 21,
                                    'money': pay_price,
                                    'describes': '用户消费(余额扣款)',
                                    'add_time': timer.get_now()
                                }
                                sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_user_balance_log',
                                                                           [value_info])
                                cmd = f"update wxapp_order set pay_type=10,pay_status=20,pay_time='{timer.get_now()}' where id={order['id']}"
                                sob.update_mysql_record(sob_handle, cmd)
                            else:
                                # 订单支付提醒
                                order_pay_send_temp(order['mini_id'], note['note_name'], rechargetime, pay_price, user['open_id'], order['id'])
                        cmd = f"update wxapp_order set recharge_time={recharge_time_total},total_price={total_price},pay_price={pay_price},first_proportion_money={first_proportion_money},second_proportion_money={second_proportion_money} where id={order['id']}"
                        sob.update_mysql_record(sob_handle,cmd)
                elif order['billtype'] == 4:#分档充满自停
                    tranche_pay(order, note, rechargetime, user, price_one, first_proportion,second_proportion)

                cmd = f"select * from wxapp_order where id={order['id']}"
                order = sob.select_mysql_record(sob_handle, cmd)
                order = order[0]
                if order['pay_type'] != 60:
                    calc_proportion_money(order)
            else:
                if order['pay_status'] == 20:  # 已支付
                    #小于五分钟退款
                    five_order_refund(order)
                else:
                    cmd = f"update wxapp_order set pay_status=20,pay_time='{timer.get_now()}' where id={order['id']}"
                    sob.update_mysql_record(sob_handle, cmd)
                cmd = f"update wxapp_order set is_invalid=1 where id={order['id']}"
                sob.update_mysql_record(sob_handle, cmd)
        cmd = f"update wxapp_order set order_status=20,endcode='{plugstatus}',powerwaste={power},endelectric={electric},end_time='{timer.get_now()}' where id={order['id']}"
        sob.update_mysql_record(sob_handle, cmd)
        cmd = f"update wxapp_pod_pileport set portstatus=0 where id={order['pileport_id']}"
        sob.update_mysql_record(sob_handle, cmd)
        # 订阅消息  结束充电通知
        cmd = f"select * from wxapp_order  where id={order['id']}"
        order = sob.select_mysql_record(sob_handle,cmd)
        try:
            over_recharge_send_temp(order[0], user['open_id'],rechargetime)
        except:
            pass
    # except:
    #     prolog.error(f'结束充电异常')



def over_recharge_send_temp(order,open_id,rechargetime):
    values_json = get_setting(order['mini_id'], 'submsg')
    template_id = values_json['order']['recharge_stop']['template_id']
    access_token = get_access_token(order['mini_id'])
    if order['endcode'] == '01':
        reason = '低于空载电流结束充电或插头被拔'
    elif order['endcode'] == '02':
        reason = '充电电流高于安全电流阈值'
    elif order['endcode'] == '03':
        reason = '充满电'
    elif order['endcode'] == 'A0':
        reason = '充满电或用户下达结束充电'
    elif order['endcode'] == '04':
        reason = '平台或用户下达充电结束'
    elif order['endcode'] == '06':
        reason = '时间已到停止充电'
    elif order['endcode'] == 'B0':
        reason = '时间已到停止充电或用户下达充电结束'
    elif order['endcode'] == '07':
        reason = '涓流充电结束'
    elif order['endcode'] == '98':
        reason = '低于空载电流结束充电或插头被拔'
    else:
        reason = '其他'
    data = {
        "character_string15": {
            "value": order['snum']},
        "amount9": {
            "value": str(order['pay_price']) +'元' if rechargetime > 5 and order['pay_type'] != 50 else '0元'},
        "thing8": {
            "value": str(int(rechargetime)) +'分钟'},
        "date10": {
            "value": order['end_time'].strftime("%Y-%m-%d %H:%M:%S")},
        "thing3": {
            "value": reason}}
    resp = wx_mini_sdk().send_tempalte_keyword(
        access_token,
        open_id,
        template_id,
        'pages/user/children/record',
        data)
    print('充电结束',resp)


def five_order_refund(order):
    print('充电不足五分钟退款。。。。')
    sob_handle = sob.sql_open(db_config)
    if order['pay_status'] == 20:  # 已支付
        if order['pay_type'] == 10:  # 余额支付
            cmd = f"update wxapp_order set pay_status=30,residue_money={order['pay_price']},refund_time='{timer.get_now()}' where id={order['id']}"
            sob.update_mysql_record(sob_handle, cmd)
            cmd = f"update wxapp_user set balance=balance+{order['pay_price']} where id={order['user_id']}"
            sob.update_mysql_record(sob_handle, cmd)
            value_info = {
                'mini_id': order['mini_id'],
                'note_id': order['note_id'],
                'type': 1,
                'start_time': str(order['start_time']),
                'end_time': timer.get_now(),
                'user_id': order['user_id'],
                'scene': 40,
                'money': order['pay_price'],
                'describes': '订单退款到余额(充电时长小于5分钟)',
                'add_time': timer.get_now()
            }
            sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_user_balance_log', [value_info])
        elif order['pay_type'] == 60:  # 虚拟支付
            cmd = f"update wxapp_order set pay_status=30,residue_money={order['pay_price']},refund_time='{timer.get_now()}' where id={order['id']}"
            sob.update_mysql_record(sob_handle, cmd)
            cmd = f"update wxapp_user set virtual_balance=virtual_balance+{order['pay_price']} where id={order['user_id']}"
            sob.update_mysql_record(sob_handle, cmd)
            value_info = {
                'mini_id': order['mini_id'],
                'note_id': order['note_id'],
                'type': 1,
                'start_time': str(order['start_time']),
                'end_time': timer.get_now(),
                'user_id': order['user_id'],
                'scene': 40,
                'money': order['pay_price'],
                'describes': '订单退款到虚拟金额(充电时长小于5分钟)',
                'add_time': timer.get_now()
            }
            sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_user_balance_log',
                                                       [value_info])
        elif order['pay_type'] == 20:  # 微信支付
            cmd = f"select * from wxapp_payinfo where mini_id={order['mini_id']}"
            payinfo = sob.select_mysql_record(sob_handle, cmd)
            if payinfo:
                payinfo = payinfo[0]
                out_refund_no = f"{timer.get_now('%Y%m%d%H%M%S')}{order['user_id']}"
                total_fee = int(order['pay_price'] * 100)
                if payinfo['pay_type'] == 2:  # 通联支付
                    tl_pay = tl_pay_sdk()
                    resp = tl_pay.tl_refunds(payinfo['orgid'], payinfo['mchid'],
                                             payinfo['apikey'],
                                             total_fee, out_refund_no,
                                             order['transaction_id'],
                                             payinfo['key_pem'])
                    if resp['retcode'] == 'SUCCESS':
                        if resp['trxstatus'] == '0000':
                            trxid = resp['trxid']  # 收银宝交易单号
                            cmd = f"update wxapp_order set order_status=20,is_invalid=1,pay_status=30,residue_money={order['pay_price']},refund_id='{trxid}',refund_time='{timer.get_now()}' where id={order['id']}"
                            sob.update_mysql_record(sob_handle, cmd)
                            value_info = {
                                'mini_id': order['mini_id'],
                                'note_id': order['note_id'],
                                'type': 1,
                                'start_time': str(order['start_time']),
                                'end_time': timer.get_now(),
                                'user_id': order['user_id'],
                                'scene': 40,
                                'money': order['pay_price'],
                                'describes': '订单退款到通联(充电时长小于5分钟)',
                                'add_time': timer.get_now()
                            }
                            sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_user_balance_log',
                                                                       [value_info])
                            invalid_dealer_order(order)
                        else:
                            cmd = f"update wxapp_order set pay_status=40 where id={order['id']}"
                            sob.update_mysql_record(sob_handle, cmd)
                    else:
                        cmd = f"update wxapp_order set pay_status=40,residue_money={order['pay_price']} where id={order['id']}"
                        sob.update_mysql_record(sob_handle, cmd)
                else:
                    notify_url = f'{REQ_HOST}/api/wx_order_fefunds_payback/{payinfo["orgid"]}'
                    print(notify_url)
                    response = wx_pay_sdk().refunds_v3(order['transaction_id'], out_refund_no,
                                            total_fee, total_fee, payinfo['mchid'], payinfo['apikey'],payinfo['key_pem'], notify_url)
                    print(response.text)
                    cmd = f"update wxapp_order set residue_money={order['pay_price']} where id={order['id']}"
                    sob.update_mysql_record(sob_handle, cmd)
            else:
                prolog.error('支付信息不完善，退款失败')
        else:
            cmd = f"update wxapp_recharge_package_order set residue_time=residue_time+{order['recharge_time']} " \
                  f"where user_id={order['user_id']} and type=2 and start_time<='{timer.get_now()}' and end_time>='{timer.get_now()}' and order_status=20"
            sob.update_mysql_record(sob_handle, cmd)
    sob.sql_close(sob_handle)


def calc_proportion_money(order):
    try:
        sob_handle = sob.sql_open(db_config)
        if order['second_proportion_money'] and order['pay_status'] == 20:
            cmd = f"update wxapp_dealer_note set freeze_money=freeze_money+{order['second_proportion_money']} where find_in_set({order['note_id']},note_id) and type=6"
            sob.update_mysql_record(sob_handle,cmd)
            cmd = f"select * from wxapp_user where find_in_set({order['note_id']},note_id) and type=6"
            account = sob.select_mysql_record(sob_handle,cmd)
            value_info = {
                'mini_id':order['mini_id'],
                'note_id':order['note_id'],
                'user_id':account[0]['id'],
                'order_id':order['id'],
                'order_price':order['pay_price'],
                'share_money':order['second_proportion_money'],
                'type':6,
                'add_time':timer.get_now(),
                'update_time':timer.get_now()
            }
            sob.insert_Or_update_mysql_record_many_new(sob_handle,'wxapp_dealer_order',[value_info])
        if order['first_proportion_money'] and order['pay_status'] == 20:
            cmd = f"update wxapp_dealer_note set freeze_money=freeze_money+{order['first_proportion_money']} where find_in_set({order['note_id']},note_id) and type=5"
            sob.update_mysql_record(sob_handle, cmd)
            cmd = f"select * from wxapp_user where find_in_set({order['note_id']},note_id) and type=5"
            account = sob.select_mysql_record(sob_handle, cmd)
            value_info = {
                'mini_id': order['mini_id'],
                'note_id': order['note_id'],
                'user_id': account[0]['id'],
                'order_id': order['id'],
                'order_price': order['pay_price'],
                'share_money': order['first_proportion_money'],
                'type': 5,
                'add_time': timer.get_now(),
                'update_time': timer.get_now()
            }
            sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_dealer_order', [value_info])
        sob.sql_close(sob_handle)
    except:
        prolog.error('柏莱分成收入异常')


def order_pay_send_temp(mini_id,note_name,rechargetime,pay_price,open_id,id):
    try:
        values_json = get_setting(mini_id, 'submsg')
        template_id = values_json['order']['pay']['template_id']
        access_token = get_access_token(mini_id)
        data = {
            "thing1": {"value": note_name},
            "thing2": {"value": str(int(rechargetime)) + '分钟'},
            "amount4": {"value": str(pay_price) + '元'},
            "thing5": {"value": '可点击进入小程序支付'}}
        wx_mini_sdk().send_tempalte_keyword(access_token, open_id, template_id,
                                            f'pagesA/pay?order_id={id}', data)
    except:
        prolog.error('订单支付提醒异常')

def calc_order_refund(order,note,rechargetime,first_proportion,second_proportion):
    sob_handle = sob.sql_open(db_config)
    if order['pay_status'] == 20: #已支付
        if note['is_refund'] == 1: # 开启退款
            residue_rechage = order['recharge_time'] * 60 - rechargetime  # 剩余分钟数
            calc_step = math.floor(residue_rechage / note['step'])
            refund_price = calc_step * note['refund_price']  # 退款金额
            if refund_price > 0:
                if order['pay_type'] == 10:  # 余额支付
                    cmd = f"update wxapp_order set residue_money={refund_price},refund_time='{timer.get_now()}',pay_price=pay_price-{refund_price} where id={order['id']}"
                    sob.update_mysql_record(sob_handle, cmd)
                    cmd = f"update wxapp_user set balance=balance+{refund_price} where id={order['user_id']}"
                    sob.update_mysql_record(sob_handle, cmd)
                elif order['pay_type'] == 60: # 虚拟余额支付
                    cmd = f"update wxapp_order set residue_money={refund_price},refund_time='{timer.get_now()}',pay_price=pay_price-{refund_price} where id={order['id']}"
                    sob.update_mysql_record(sob_handle, cmd)
                    cmd = f"update wxapp_user set virtual_balance=virtual_balance+{refund_price} where id={order['user_id']}"
                    sob.update_mysql_record(sob_handle, cmd)
                elif order['pay_type'] == 20: # 微信支付
                    cmd = f"select * from wxapp_payinfo where mini_id={order['mini_id']}"
                    payinfo = sob.select_mysql_record(sob_handle, cmd)
                    if payinfo:
                        payinfo = payinfo[0]
                        out_refund_no = f"{timer.get_now('%Y%m%d%H%M%S')}{order['user_id']}"
                        refund_fee = int(refund_price * 100)
                        total_fee = int(order['total_price'] * 100)
                        if payinfo['pay_type'] == 2:  # 通联支付
                            tl_pay = tl_pay_sdk()
                            resp = tl_pay.tl_refunds(payinfo['orgid'], payinfo['mchid'],
                                                     payinfo['apikey'],
                                                     refund_fee, out_refund_no,
                                                     order['transaction_id'],
                                                     payinfo['key_pem'])
                        else:
                            resp=wx_pay_sdk().refunds_v3(order['transaction_id'], out_refund_no,
                                                    refund_fee, total_fee, payinfo['mchid'], payinfo['apikey'],payinfo['key_pem'])
                            print(resp.text)


                        cmd = f"update wxapp_order set residue_money={refund_price},refund_time='{timer.get_now()}',pay_price=pay_price-{refund_price} where id={order['id']}"
                        sob.update_mysql_record(sob_handle, cmd)

                first_proportion_money = order['pay_price'] * (first_proportion / 100)  # 一级（代理商）分成
                second_proportion_money = order['pay_price'] * (second_proportion / 100)  # 二级（物业）分成
                cmd = f"update wxapp_order set first_proportion_money={first_proportion_money},second_proportion_money={second_proportion_money} where id={order['id']}"
                sob.update_mysql_record(sob_handle, cmd)
    sob.sql_close(sob_handle)


def calc_order_tranche_fefund(order,note,rechargetime,first_proportion,second_proportion):
    '''分档充电退款'''
    print('分档充电退款')
    sob_handle = sob.sql_open(db_config)
    if order['pay_status'] == 20:  # 已支付
        if order['pay_type'] == 10 or order['pay_type'] == 20 or order['pay_type'] == 60:
            if note['step'] == 1: #1分钟
                rechargetime = rechargetime / 60  # 真实充电时长（小时）
            else:
                rechargetime = math.ceil(rechargetime / 60)  # 向上取整充电时长（小时）
            rechargetime = rechargetime if rechargetime < order['recharge_time'] else order['recharge_time']
            if order['order_status'] == 20:
                end_time = order['end_time'].strftime("%Y-%m-%d %H:%M:%S")
            else:
                end_time = timer.get_now()
            end_times = end_time[:10]
            start_time = order['start_time'].strftime("%Y-%m-%d %H:%M:%S")
            start_times = start_time[:10]
            # try:
            if start_times == end_times:
                table_name = f'wxapp_pod_port_electric_{start_times}'
                table_name = table_name.replace('-', '_')
                cmd = f"select portelectric from {table_name} where pile_id={order['pile_id']} and portnum={order['portnum']} and add_time>'{start_time}' and add_time<'{end_time}'"
                pod_port_electric = sob.select_mysql_record(sob_handle,cmd)
            else:
                table_name = f'wxapp_pod_port_electric_{start_times}'
                table_name = table_name.replace('-', '_')
                cmd = f"select portelectric from {table_name} where pile_id={order['pile_id']} and portnum={order['portnum']} and add_time>'{start_time}' and add_time<'{end_time}'"
                pod_port_electric_start = sob.select_mysql_record(sob_handle, cmd)
                table_name = f'wxapp_pod_port_electric_{end_times}'
                table_name = table_name.replace('-', '_')
                cmd = f"select portelectric from {table_name} where pile_id={order['pile_id']} and portnum={order['portnum']} and add_time>'{start_time}' and add_time<'{end_time}'"
                pod_port_electric_end = sob.select_mysql_record(sob_handle, cmd)
                pod_port_electric = pod_port_electric_start + pod_port_electric_end
            pod_port_electric = sorted(pod_port_electric,key=lambda pod_port_electric: pod_port_electric["portelectric"],
                                          reverse=True)  # 排序
            portelectric = pod_port_electric[0]['portelectric'] if pod_port_electric else 0#前x分钟最高电流
            cmd = f"select * from wxapp_bill_tranche where note_id={note['id']} and start_section<={portelectric} and end_section>={portelectric}"
            bill_tranche = sob.select_mysql_record(sob_handle,cmd)
            if bill_tranche:
                bill_tranche = bill_tranche[0]
            else:
                cmd = f"select * from wxapp_bill_tranche where note_id={note['id']} order by sort"
                bill_tranche = sob.select_mysql_record(sob_handle, cmd)
                bill_tranche = bill_tranche[0]
            price_one = worry_free_price(note['mini_id'])
            if order['pay_price'] == note['predict_price'] + price_one:
                refund_price = order['pay_price'] - bill_tranche['price'] * rechargetime - price_one  # 退款金额
            else:
                refund_price = order['pay_price'] - bill_tranche['price'] * rechargetime  # 退款金额
            print('refund_price',refund_price)
            if refund_price > 0:
                if order['pay_type'] == 10:  # 余额支付
                    cmd = f"update wxapp_order set residue_money={refund_price},refund_time='{timer.get_now()}',pay_price=pay_price-{refund_price} where id={order['id']}"
                    sob.update_mysql_record(sob_handle, cmd)
                    cmd = f"update wxapp_user set balance=balance+{refund_price} where id={order['user_id']}"
                    sob.update_mysql_record(sob_handle, cmd)
                elif order['pay_type'] == 60:  # 虚拟余额支付
                    cmd = f"update wxapp_order set residue_money={refund_price},refund_time='{timer.get_now()}',pay_price=pay_price-{refund_price} where id={order['id']}"
                    sob.update_mysql_record(sob_handle, cmd)
                    cmd = f"update wxapp_user set virtual_balance=virtual_balance+{refund_price} where id={order['user_id']}"
                    sob.update_mysql_record(sob_handle, cmd)
                elif order['pay_type'] == 20:  # 微信支付
                    cmd = f"select * from wxapp_payinfo where mini_id={order['mini_id']}"
                    payinfo = sob.select_mysql_record(sob_handle, cmd)
                    if payinfo:
                        payinfo = payinfo[0]
                        out_refund_no = f"{timer.get_now('%Y%m%d%H%M%S')}{order['user_id']}"
                        refund_fee = int(refund_price * 100)
                        total_fee = int(order['total_price'] * 100)
                        if payinfo['pay_type'] == 2:  # 通联支付
                            tl_pay = tl_pay_sdk()
                            resp = tl_pay.tl_refunds(payinfo['orgid'], payinfo['mchid'],
                                                     payinfo['apikey'],
                                                     refund_fee, out_refund_no,
                                                     order['transaction_id'],
                                                     payinfo['key_pem'])
                        else:
                            wx_pay_sdk().refunds_v3(order['transaction_id'], out_refund_no,
                                                    refund_fee, total_fee, payinfo['mchid'], payinfo['apikey'],payinfo['key_pem'])

                        cmd = f"update wxapp_order set residue_money={refund_price},refund_time='{timer.get_now()}',pay_price=pay_price-{refund_price} where id={order['id']}"
                        sob.update_mysql_record(sob_handle, cmd)

                first_proportion_money = order['pay_price'] * (first_proportion / 100)  # 一级（代理商）分成
                second_proportion_money = order['pay_price'] * (second_proportion / 100)  # 二级（物业）分成
                cmd = f"update wxapp_order set first_proportion_money={first_proportion_money},second_proportion_money={second_proportion_money} where id={order['id']}"
                sob.update_mysql_record(sob_handle, cmd)
            # except:
            #     prolog.error(f"分档退款失败:order_id:{order['id']}")
    sob.sql_close(sob_handle)




def tranche_pay(order,note,rechargetime,user,price_one,first_proportion,second_proportion):
    sob_handle = sob.sql_open(db_config)
    if note['step'] == 1:  # 1分钟
        recharge_time = rechargetime / 60  # 真实充电时长（小时）
    else:
        recharge_time = math.ceil(rechargetime / 60)  # 向上取整充电时长（小时）
    recharge_time_total = recharge_time
    start_time = order['start_time'].strftime("%Y-%m-%d %H:%M:%S")
    cmd = f"select * from wxapp_recharge_package_order where user_id={order['user_id']} and note_id={note['id']} and pay_status=20 and type=2 and end_time>='{start_time}' and order_status=20 and residue_time>0"
    recharge_package_orders = sob.select_mysql_record(sob_handle, cmd)
    for recharge in recharge_package_orders:
        if recharge['is_charge_buy'] == 1:
            price_one = 0
    is_pay = False
    first_proportion_money = 0
    second_proportion_money = 0
    total_price = 0
    pay_price = 0
    for recharge in recharge_package_orders:
        if recharge['end_time'] > datetime.datetime.strptime(order['end_time'], '%Y-%m-%d %H:%M:%S'):  # 套餐包结束时间大于充电订单结束时间
            if recharge['residue_time'] >= recharge_time:
                cmd = f"update wxapp_recharge_package_order set residue_time=residue_time-{recharge_time} where id={recharge['id']}"
                sob.update_mysql_record(sob_handle, cmd)
                cmd = f"update wxapp_order set pay_price=0,pay_type=30,pay_status=20,pay_time='{timer.get_now()}' where id={order['id']}"
                sob.update_mysql_record(sob_handle, cmd)
                is_pay = True  # 套餐扣费
                break
            else:
                recharge_time = recharge_time - recharge['residue_time']  # 需要扣费的时间
                cmd = f"update wxapp_recharge_package_order set residue_time=0 where id={recharge['id']}"
                sob.update_mysql_record(sob_handle, cmd)
        else:
            stime = (timer.time2timestamp(recharge['end_time'].strftime("%Y-%m-%d %H:%M:%S")) - timer.time2timestamp(
                order['start_time'].strftime("%Y-%m-%d %H:%M:%S"))) / 3600  # 到期前套餐包使用时间
            if recharge['residue_time'] >= stime:
                recharge_time = (timer.time2timestamp(order['end_time'].strftime("%Y-%m-%d %H:%M:%S")) - timer.time2timestamp(
                    recharge['end_time'].strftime("%Y-%m-%d %H:%M:%S"))) / 3600  # 需要扣费的时间
            else:
                recharge_time = recharge_time - recharge['residue_time']  # 需要扣费的时间
                cmd = f"update wxapp_recharge_package_order set residue_time=0 where id={recharge['id']}"
                sob.update_mysql_record(sob_handle, cmd)
    if is_pay == False:  # 套餐时间不足
        if order['order_status'] == 20:
            end_time = order['end_time'].strftime("%Y-%m-%d %H:%M:%S")
        else:
            end_time = timer.get_now()
        end_times = end_time[:10]
        start_time = order['start_time'].strftime("%Y-%m-%d %H:%M:%S")
        start_times = start_time[:10]
        if start_times == end_times:
            table_name = f'wxapp_pod_port_electric_{start_times}'
            table_name = table_name.replace('-', '_')
            cmd = f"select portelectric from {table_name} where pile_id={order['pile_id']} and portnum={order['portnum']} and add_time>'{start_time}' and add_time<'{end_time}'"
            pod_port_electric = sob.select_mysql_record(sob_handle, cmd)
        else:
            table_name = f'wxapp_pod_port_electric_{start_times}'
            table_name = table_name.replace('-', '_')
            cmd = f"select portelectric from {table_name} where pile_id={order['pile_id']} and portnum={order['portnum']} and add_time>'{start_time}' and add_time<'{end_time}'"
            pod_port_electric_start = sob.select_mysql_record(sob_handle, cmd)
            table_name = f'wxapp_pod_port_electric_{end_times}'
            table_name = table_name.replace('-', '_')
            cmd = f"select portelectric from {table_name} where pile_id={order['pile_id']} and portnum={order['portnum']} and add_time>'{start_time}' and add_time<'{end_time}'"
            pod_port_electric_end = sob.select_mysql_record(sob_handle, cmd)
            pod_port_electric = pod_port_electric_start + pod_port_electric_end
        pod_port_electric = sorted(pod_port_electric, key=lambda pod_port_electric: pod_port_electric["portelectric"],
                                   reverse=True)  # 排序
        portelectric = pod_port_electric[0]['portelectric']  # 前x分钟最高电流
        cmd = f"select * from wxapp_bill_tranche where note_id={note['id']} and start_section<={portelectric} and end_section>={portelectric}"
        bill_tranche = sob.select_mysql_record(sob_handle, cmd)
        if bill_tranche:
            bill_tranche = bill_tranche[0]
        else:
            cmd = f"select * from wxapp_bill_tranche where note_id={note['id']} order by sort"
            bill_tranche = sob.select_mysql_record(sob_handle, cmd)
            bill_tranche = bill_tranche[0]
        pay_price = bill_tranche['price'] * recharge_time + price_one  # 需要付款金额
        total_price = bill_tranche['price'] * recharge_time + price_one

        first_proportion_money = total_price * (first_proportion / 100)  # 一级（代理商）分成
        second_proportion_money = total_price * (second_proportion / 100)  # 二级（物业）分成
        if user['virtual_balance'] >= pay_price:
            cmd = f"update wxapp_user set virtual_balance=virtual_balance-{pay_price} where id={order['user_id']}"
            sob.update_mysql_record(sob_handle, cmd)
            value_info = {
                'mini_id': order['mini_id'],
                'note_id': order['note_id'],
                'type': 1,
                'start_time': str(order['start_time']),
                'end_time': str(order['end_time']),
                'user_id': order['user_id'],
                'scene': 21,
                'money': pay_price,
                'describes': '用户消费(虚拟钱包扣款)',
                'add_time': timer.get_now()
            }
            sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_user_balance_log', [value_info])
            cmd = f"update wxapp_order set pay_type=60,pay_status=20,pay_time='{timer.get_now()}' where id={order['id']}"
            sob.update_mysql_record(sob_handle, cmd)
        elif user['balance'] >= pay_price:
            cmd = f"update wxapp_user set balance=balance-{pay_price} where id={order['user_id']}"
            sob.update_mysql_record(sob_handle, cmd)
            value_info = {
                'mini_id': order['mini_id'],
                'note_id': order['note_id'],
                'type': 1,
                'start_time': str(order['start_time']),
                'end_time': str(order['end_time']),
                'user_id': order['user_id'],
                'scene': 21,
                'money': pay_price,
                'describes': '用户消费(余额扣款)',
                'add_time': timer.get_now()
            }
            sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_user_balance_log',
                                                       [value_info])
            cmd = f"update wxapp_order set pay_type=10,pay_status=20,pay_time='{timer.get_now()}' where id={order['id']}"
            sob.update_mysql_record(sob_handle, cmd)
        else:
            # 订单支付提醒
            order_pay_send_temp(order['mini_id'], note['note_name'], rechargetime, pay_price, user['open_id'],
                                order['id'])
    cmd = f"update wxapp_order set recharge_time={recharge_time_total},total_price={total_price},pay_price={pay_price},first_proportion_money={first_proportion_money},second_proportion_money={second_proportion_money} where id={order['id']}"
    sob.update_mysql_record(sob_handle, cmd)
    sob.sql_close(sob_handle)




def shua_card_rechage(pod_pile,cardnohex,portnum,onlytag,piletype=1):
    print('shua_card_rechage')
    lastrowid = ''
    sob_handle = sob.sql_open(db_config)
    pod_pile = pod_pile[0]
    # 刷卡判断卡的状态:
    repcode = '01'
    pay_type = 40  # 刷卡充电
    cmd = f"select * from wxapp_door_idno where idno='{cardnohex}' and note_id={pod_pile['note_id']}"
    user_card = sob.select_mysql_record(sob_handle, cmd)
    if not user_card:
        repcode = '02'  # 无效卡
    else:
        user_card = user_card[0]
        user_id = user_card['user_id']
        note_id = user_card['note_id']
        # 查看是否有充电中的订单
        cmd = f"select * from wxapp_order where user_id={user_id} and order_status=10"
        orders = sob.select_mysql_record(sob_handle, cmd)
        # 查看是否有已完成未支付的订单
        cmd = f"select * from wxapp_order where user_id={user_id} and pay_status=10 and (order_status=11 or order_status=20) and pay_price!=0"
        pay_orders = sob.select_mysql_record(sob_handle, cmd)
        # 查看账户是否冻结
        cmd = f"select * from wxapp_user where id={user_id} and is_freeze=1"
        user = sob.select_mysql_record(sob_handle, cmd)
        if orders or pay_orders or user:
            repcode = '04'  # 账号被占用
        # 端口是否被占用
        cmd = f"select * from wxapp_pod_pileport where note_id={note_id} and serialnum='{pod_pile['serialnum']}' and portnum={portnum}"
        pod_pileport = sob.select_mysql_record(sob_handle, cmd)
        if pod_pileport:
            pod_pileport = pod_pileport[0]
            if pod_pileport['portstatus'] != 0:
                repcode = '05'  # 端口被占用
        if repcode == '01':
            cmd = f"select * from wxapp_user where id={user_id}"
            user = sob.select_mysql_record(sob_handle, cmd)
            user = user[0]
            # 获取社区信息
            cmd = f"select * from wxapp_note where id={note_id}"
            notes = sob.select_mysql_record(sob_handle, cmd)
            note = notes[0]
            # 获取白名单用户
            cmd = f"select * from wxapp_white_list where user_id={user_id} and note_id={note_id} and special_end>'{timer.get_now()}' and special_start<'{timer.get_now()}' and type=2"
            white_user = sob.select_mysql_record(sob_handle, cmd)
            if not white_user:  # 是否是白名单
                cmd = f"select * from wxapp_recharge_package_order where user_id={user_id} and note_id={note_id} and pay_status=20 and type=2 and start_time<='{timer.get_now()}' and end_time>='{timer.get_now()}' and order_status=20 and residue_time>0"
                recharge_package_orders = sob.select_mysql_record(sob_handle, cmd)
                if not recharge_package_orders:  # 是否有充电包
                    balance = user['balance']
                    virtual_balance = user['virtual_balance']
                    if virtual_balance < note['predict_price']:
                        if balance < note['predict_price']:
                            repcode = '03'  # 余额不足
            else:
                pay_type = 50  # 白名单用户

    if repcode == '01':
        print(44)
        order_id = f"{timer.get_now(format='%Y%m%d%H%M%S')}{user_id}"
        value_info = {
            'order_id': order_id,
            'mini_id': user['mini_id'],
            'note_id': note_id,
            'user_id': user_id,
            'pile_id': pod_pile['id'],
            'pileport_id': pod_pileport['id'],
            'snum': pod_pile['snum'],
            'start_time': timer.get_now(),
            'portnum': portnum,
            'order_status': 1,
            'pay_status': 10,
            'is_charge_buy': 0,
            'billtype': 2 if note['bill_type'] == 0 else 4,
            'pay_type': pay_type,
            'onlytag': onlytag[:4] if piletype==1 else onlytag,
            'add_time':timer.get_now()
        }
        lastrowid = sob.insert_Or_update_mysql_record_many_new(sob_handle, 'wxapp_order', [value_info])
        cmd = f"update wxapp_pod_pileport set portstatus=1 where id={pod_pileport['id']}"
        sob.update_mysql_record(sob_handle, cmd)
    sob.sql_close(sob_handle)
    return repcode,lastrowid

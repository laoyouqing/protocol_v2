import time
import uuid

from orm import Model, StringField, FloatField, TextField, TinyintField, IntegerField, DatetimeField
from tool.wf_time_new import wf_time_new

timer = wf_time_new()


class Ev_pod_idno(Model):
    __table__ = 'wxapp_door_idno'

    id = IntegerField(primary_key=True)#id
    mini_id = IntegerField()#小程序id
    user_id = IntegerField()#用户id
    note_id = IntegerField()#社区id
    idno = StringField(ddl='varchar(50)')  # 门禁卡ID
    rfid = StringField(ddl='varchar(50)')  # rfid卡ID
    add_time = DatetimeField(default=timer.get_now())#创建时间
    update_time = DatetimeField(default=timer.get_now())#更新时间


class User_white_list(Model):
    __table__ = 'wxapp_white_list'

    id = IntegerField(primary_key=True)  # id
    mini_id = IntegerField()  # 小程序id
    user_id = IntegerField()  # 用户id
    note_id = IntegerField()  # 社区id
    type = TinyintField()  # 套餐类型 (1:停车包 2:停车加充电包)
    special_start = DatetimeField() #有效开始时间
    special_end = DatetimeField()  #有效结束时间
    remarks = StringField(ddl='varchar(255)')  # 备注
    add_time = DatetimeField(default=timer.get_now())


class User(Model):
    __table__ = 'wxapp_user'

    id = IntegerField(primary_key=True)  # id
    mini_id = IntegerField()  # 小程序id
    note_id = StringField(ddl='varchar(30)') #社区id
    authority_id = IntegerField() #权限id
    mobile = StringField(ddl='varchar(11)')
    password = StringField(ddl='varchar(100)')
    open_id = StringField(ddl='varchar(255)')
    nickname = StringField(ddl='varchar(255)')
    avatar = StringField(ddl='varchar(255)')
    gender = TinyintField(default=0)
    is_freeze = IntegerField(default=0)  # 是否冻结 1是 0否
    is_manage = IntegerField(default=0)  # 账号类型0:微信用户 1:系统管理员 2客服 3:财务 4:工程 5:代理商 6:物业
    balance = FloatField()  #用户可用余额
    virtual_balance = FloatField()  # 虚拟余额
    add_time = DatetimeField(default=timer.get_now())



class Ev_recharge_package_order(Model):
    __table__ = 'wxapp_recharge_package_order'

    id = IntegerField(primary_key=True)  # id
    order_id = StringField(ddl='varchar(255)')  # 订单id
    mini_id = IntegerField()  # 小程序id
    user_id = IntegerField()  # 用户id
    note_id = IntegerField()  # 社区id
    rechargeuser_id = IntegerField()  # 代充值用户(第三方)
    package_id = IntegerField()  # 套餐包id
    pay_type = TinyintField()  # 支付方式(10余额支付 20微信支付 30混合支付 40管理员代买)
    pay_price = FloatField()  # 用户支付金额
    pay_status = TinyintField()  # 支付状态(10待支付 20已支付)
    order_status = TinyintField()  # 订单状态(10未完成 20已完成 30退款中 40已退款 50退款被拒绝 60退款异常)
    pay_time = DatetimeField()  # 付款时间
    refund_time = DatetimeField()  # 退款时间
    transaction_id = StringField(ddl='varchar(30)')  # 微信支付交易号
    # plan_type = TinyintField()  #套餐类型 (1:月卡 2:季卡 3:年卡 4:其他)
    type = TinyintField()  # 套餐类型 (1:停车包 2:停车加充电包)
    plan_name = StringField(ddl='varchar(255)')  # 套餐名称
    recharge_time = IntegerField()  # 充电时间
    residue_time = IntegerField()  # 剩余充电时间
    is_effect = IntegerField()  # 是否立即生效(0否(次月) 1是)
    is_auto_renew = IntegerField()  # 是否自动续费(0否 1是)
    is_use = TinyintField()  # 是否有效(0否 1是)
    is_renew = TinyintField()  # 是否续费(0否 1是)
    is_charge_buy = TinyintField()  # 是否购买无忧充电(0否 1是)
    is_invalid = TinyintField()  # 订单是否失效(0未失效 1已失效)
    is_settled = TinyintField()  # 是否已结算佣金(0未结算 1已结算)
    first_proportion_money = FloatField()  # 一级分成金额
    second_proportion_money = FloatField()  # 二级分成金额
    add_time = DatetimeField(default=timer.get_now())
    start_time = DatetimeField()  # 开始时间
    end_time = DatetimeField()  # 到期时间



class Ev_note(Model):
    __table__ = 'wxapp_note'

    id = IntegerField(primary_key=True)  # id
    mini_id = IntegerField()  # 小程序id
    note_name = StringField(ddl='varchar(255)')#note名称
    province_id = IntegerField()#所在省份id
    city_id = IntegerField()#所在城市id
    region_id = IntegerField()#所在辖区id
    address = StringField(ddl='varchar(100)')#详细地址(社区楼栋位置)
    longitude = StringField(ddl='varchar(50)')#经度
    latitude = StringField(ddl='varchar(50)')#纬度
    summary = StringField(ddl='varchar(1000)')#NOTE简介
    status = TinyintField()#状态(0停止 1正常)
    is_ind_dealer = TinyintField()  # 是否开启单独分成(0关闭 1开启)
    bill_type = TinyintField(default=0)  # 计费类型(0按时 1分档)
    predict_price = FloatField()  # 预扣金额
    first_proportion = TinyintField()  # 一级分成比例(代理商)
    second_proportion = TinyintField()  # 二级分成比例(社区)
    free_time = IntegerField()  # 免费停放时长（分钟）
    money = FloatField()  # 门禁费用单次
    is_refund = IntegerField(default=0)  # 是否开启充电时长不足退款(1是 0否)
    is_temporary_site = IntegerField(default=0)  # 是否是临时停场地(1是 0否)
    step = TinyintField()  # 步长/小时
    refund_price = FloatField()  # 步长/退款单价
    add_time = DatetimeField(default=timer.get_now())
    update_time = DatetimeField(default=timer.get_now())


class Ev_setting(Model):
    __table__ = 'wxapp_setting'

    id = IntegerField(primary_key=True)  # id
    mini_id = IntegerField()  # 小程序id
    title = StringField(ddl='varchar(30)')  # 设置项标示
    describes = StringField(ddl='varchar(255)')  # 设置项描述
    values_json = TextField()  # 设置内容(json格式)
    add_time = DatetimeField(default=timer.get_now())
    update_time = DatetimeField(default=timer.get_now())



class User_balance_log(Model):
    __table__ = 'wxapp_user_balance_log'

    id = IntegerField(primary_key=True)  # id
    mini_id = IntegerField()  # 小程序id
    user_id = IntegerField()  # 用户id
    note_id = IntegerField()  # 社区id
    rechargeuser_id = IntegerField()  # 充值用户id
    type = IntegerField()  #消费类型 1 充电 2 门禁 3 其他
    start_time = DatetimeField()  # 开始时间
    end_time = DatetimeField()  # 结束时间
    scene = IntegerField()  #余额变动场景(10用户充值 20用户消费(微信扣款) 21用户消费(钱包扣款) 30管理员操作 40订单退款 50：赠送 60代他充值)
    money = FloatField()
    describes = StringField(ddl='varchar(500)')
    remark = StringField(ddl='varchar(500)')
    add_time = DatetimeField(default=timer.get_now())



class Member_miniapp(Model):
    __table__ = 'wxapp_mini'

    id = IntegerField(primary_key=True)  # id
    mini_name = StringField(ddl='varchar(50)') #小程序名称
    authorizer_appid = StringField(ddl='varchar(32)')
    secret = StringField(ddl='varchar(32)')
    access_token = StringField(ddl='varchar(32)')
    expird_time = DatetimeField()
    add_time = DatetimeField(default=timer.get_now())


class Ev_dealer_note(Model):
    __table__ = 'wxapp_dealer_note'

    id = IntegerField(primary_key=True)  # id
    mini_id = IntegerField()  # 小程序id
    note_id = StringField(ddl='varchar(32)')  # 社区id
    type = IntegerField()  #角色(5:代理商  6物业)
    account_id = IntegerField()#(账户id)
    money = FloatField()#当前可提现佣金
    freeze_money = FloatField()#已冻结佣金
    total_money = FloatField()#累积提现佣金
    add_time = DatetimeField(default=timer.get_now())
    update_time = DatetimeField(default=timer.get_now())


class Ev_dealer_order(Model):
    __table__ = 'wxapp_dealer_order'

    id = IntegerField(primary_key=True)  # id
    mini_id = IntegerField()  # 小程序id
    note_id = IntegerField()  # 社区id
    type = IntegerField()  # 角色(5:代理商  6物业)
    account_id = IntegerField()  # (账户id)
    order_id = StringField(ddl='varchar(50)')  # 订单id
    order_price = FloatField()#订单支付总金额
    share_money = FloatField()#分成金额
    is_invalid = TinyintField()#订单是否失效(0未失效 1已失效)
    is_settled = TinyintField()#是否已结算佣金(0未结算 1已结算)
    settle_time = DatetimeField()#结算时间
    add_time = DatetimeField(default=timer.get_now())
    update_time = DatetimeField(default=timer.get_now())


class Member_payinfo(Model):
    __table__ = 'wxapp_payinfo'

    id = IntegerField(primary_key=True)  # id
    mini_id = IntegerField()  # 小程序id
    orgid = StringField(ddl='varchar(50)') #共享集团号/代理商参数时必填
    pay_type = TinyintField(default=1)  # 1.普通支付 2.通联支付
    mchid = StringField(ddl='varchar(50)')
    apikey = StringField(ddl='varchar(255)')
    cert_pem = TextField()
    key_pem = TextField()



class Ev_pod_door(Model):
    __table__ = 'wxapp_pod_door'

    id = IntegerField(primary_key=True)  # id
    mini_id = IntegerField()  # 小程序id
    note_id = IntegerField()  # 社区id
    title = StringField(ddl='varchar(50)')#标题
    serialnum = StringField(ddl='varchar(50)')#设备序列号
    doorindex = IntegerField()#门号(01,02,03,04)
    readhead_num = IntegerField()  # 读头数（1单读头 2双读头）
    status = TinyintField()#状态(0离线 1在线)
    lastip = StringField(ddl='varchar(50)')#最后上线IP
    add_time = DatetimeField(default=timer.get_now())
    update_time = DatetimeField(default=timer.get_now())


def next_id():
    return '%015d%s000' % (int(time.time() * 1000), uuid.uuid4().hex)

class Ev_pod_door_log(Model):
    __table__ = 'wxapp_user_door_log'

    id = StringField(primary_key=True, default=next_id, ddl='varchar(50)')#id
    mini_id = IntegerField()  # 小程序id
    user_id = IntegerField()  # 用户id
    note_id = IntegerField()  # 社区id
    serialnum = StringField(ddl='varchar(50)')  # 设备序列号
    idno = StringField(ddl='varchar(50)')  # 门禁卡ID
    type = IntegerField()  # 进门类型 0扫码 1刷卡 (or)rfid
    doorindex = IntegerField()  # 门号(01,02,03,04)
    doorio = IntegerField()  # 进门01/出门02
    status = TinyintField()  # 状态(0不通过 1通过)
    pay_type = TinyintField()  # 支付方式(1白名单+免费 2包月 3余额 4微信)
    pay_status = TinyintField()  # 支付状态(1未支付 2已付款 3已退款)    支付状态(1未支付 2免费 3包月 4余额 5微信)
    money = FloatField()  # 支付金额
    residue_money = FloatField()  # 退款金额
    transaction_id = StringField(ddl='varchar(50)')  # 微信交易号
    pay_time = DatetimeField()  # 付款时间
    is_due = IntegerField()   #是否欠费 0否 1是
    due_time = DatetimeField()   #欠费时间
    refund_time = DatetimeField()   #退款时间
    is_invalid = TinyintField()  # 订单是否失效(0未失效 1已失效)
    is_settled = TinyintField()  # 是否已结算佣金(0未结算 1已结算)
    first_proportion_money = FloatField()  # 一级分成金额
    second_proportion_money = FloatField()  # 二级分成金额
    refund_id = StringField(ddl='varchar(50)')  # 微信退款单号
    user_received_account = StringField(ddl='varchar(50)')  # 退款入账账户
    reason = StringField(ddl='varchar(50)')  # 原因代码
    add_time = DatetimeField()
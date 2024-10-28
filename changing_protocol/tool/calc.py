import datetime
import math
import time


def low_high(data):
    # 163f2109  == 09213f16
    isetp = math.ceil(len(data) / 8)
    repdata = ''
    for i in range(1, isetp + 1):
        tmp = data[(i - 1) * 8: 8 * i]
        low = tmp[2:4] + tmp[0:2]
        high = tmp[6:] + tmp[4:6]
        repdata = high + low + repdata
    return repdata


def high_low(data):
    # 163f2109  == 09213f16
    isetp = math.ceil(len(data) / 8)
    repdata = ''
    for i in range(1, isetp + 1):
        tmp = data[(i - 1) * 8: 8 * i]
        low = tmp[2:4] + tmp[0:2]
        high = tmp[6:] + tmp[4:6]
        repdata = high + low + repdata
    return repdata


base = [str(x) for x in range(10)] + [chr(x) for x in range(ord('A'), ord('A') + 6)]


def dec2hex(string_num):
    num = int(string_num)
    mid = []
    while True:
        if num == 0:
            break
        num, rem = divmod(num, 16)
        mid.append(base[rem])
    return ''.join([str(x) for x in mid[::-1]])



def getimestamp():
    now_tm = (datetime.datetime.now().strftime('%Y%m%d%H%M%S'))
    time_array = time.strptime(now_tm, "%Y%m%d%H%M%S")
    stamp_tm = int(time.mktime(time_array))
    data = hex(stamp_tm)[2:].zfill(8)
    return data


def uchar_checksum(data, byteorder='little'):
    '''
    char_checksum 按字节计算校验和。每个字节被翻译为无符号整数
    @param data: 字节串
    @param byteorder: 大/小端
    '''
    length = len(data)
    checksum = 0
    for i in range(0, length):
        checksum += int.from_bytes(data[i:i + 1], byteorder, signed=False)
        checksum &= 0xFF  # 强制截断

    return checksum
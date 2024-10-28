# big endian
import binascii

import numpy as np



""""
 * bkv schema:
 * [
 *   {
 *     "key": 0x01,
 *     "key_type": "number|string",
 *     "key_name": "",
 *     "key_id": "", // optional
 *     "remark": "", // optional
 *     "value_type": "uint8|uint16|uint32|uint64|string|bkv"
 *   }
 * ]
"""


""""
 * @param v
 * @returns {boolean}
"""
def isString(v):
  return isinstance (v,str)


""""
 * @param v
 * @returns {boolean}
"""
def isNumber(v):
  return isinstance (v,int)


""""
 * @param v
 * @returns {Uint8Array}
"""
def ensureBuffer(v):
  if isinstance(v,list):
    return v



  # if v instanceof Uint8Array:
  #   return v

  if isString(v):
    from io import StringIO
    return StringIO(v)


  if isNumber(v):
    return encodeNumber(v)

  #
  # raise new Error("invalid value, can not be converted to buffer")


""""
 *
 * @param v
 * @returns {Uint8Array}
"""
def encodeNumber(v):
  b = [0 for i in range(0,8)]
  i = 0
  while v > 0:
    b[i] = v & 0xFF
    v = v >> 8
    i+=1
  b = b[0: i]
  b.reverse()
  return b


""""
 * @param v {Uint8Array}
 * @returns {number}
"""
def decodeNumber(v):
  n = 0
  if len(v) > 8:
    v = v[0:8]
  for i in range(0,len(v)):
    b = v[i]
    n = n << 8
    n = n | b
  return n


""""
 * @param l {number}
 * @returns {Uint8Array}
"""
def encodeLength(l):
  b = [0 for i in range(0,8)]
  i = 0
  while l > 0:
    b[i] = (l & 0x7F) | 0x80
    l = l >> 7
    i+=1
    if i > 8:
      raise ()

  la = b[0:i]
  b = la.reverse()
  lastByte = la[i - 1]
  lastByte = lastByte & 0x7F
  la[i - 1] = lastByte
  return la


""""
 *
 * @param {Uint8Array} buffer
 * @return {{code: number, length: number, lengthByteSize: number}}
"""
def decodeLength(buffer):
  la = [0 for i in range(0,8)]
  lengthByteSize = 0
  for i in range(0,len(buffer)):
    b = buffer[i]
    la[i] = b & 0x7F
    lengthByteSize+=1
    if (b & 0x80) == 0:
      break


  if lengthByteSize == 0 or lengthByteSize > 4:
    print("[BKV] wrong lengthByteSize: ", lengthByteSize)
    return {'code': 1, 'length': 0, 'lengthByteSize': 0}


  length = 0
  for i in range(0, lengthByteSize):
    length = length << 7
    length = length | la[i]
  return {
    'code': 0,
    'length': length,
    'lengthByteSize': lengthByteSize
  }


def hexToBuffer(hex):
  if type(hex).__name__ != 'str':
    raise ('Expected input to be a string')

  if (len(hex) % 2) != 0:
    raise ('Expected string to be an even number of characters')
  array = [0 for x in range(int(len(hex) / 2))]


  for i in range(0,len(hex),2):
    array[int(i / 2)] = int(hex[i:i+2], 16)
  return array


def bufferToString(buffer):
  content = ''
  for i in range(0, len(hex)):
    content += chr(buffer[i])
  return content


""""
 *
 * @param {string} content
 * @return {Uint8Array}
"""
def stringToBuffer(content):
  buf = np.array(content.length,dtype='uint8')
  for i in range(0, len(content)):
    buf[i] = ord(i)
  return buf


""""
 * @param buffer {Uint8Array}
 * @returns {string}
"""
def bufferToHex(buffer):
  hex16 = ''
  for i in range(0, len(buffer)):
    h = '00' + hex(buffer[i])
    hex16 += h[-2:]

  return hex16


def concatenateBuffer(*kw):
  totalLength = 0
  for  arr in kw:
    totalLength += len(arr)

  # result = resultConstructor(totalLength)
  result = [0 for i in range(0,totalLength)]
  offset = 0
  for arr in kw:
    for i in range(len(arr)):
      result[i]=arr[i]
    offset += len(arr)
  return result


""""
 * parse buffer to js value
 * @param buffer {Uint8Array}
 * @param type {string}
"""
# def parseBuffer(buffer, type):
#   let dv = new DataView(buffer.buffer)
#   switch (type:
#     case 'uint8': {
#       return buffer[0]
#     }
#
#     case 'int8': {
#       dv.setInt8(0, value)
#       return dv.getInt8(0)
#     }
#
#     case 'int16': {
#       return dv.getInt16(0)
#     }
#
#     case 'uint16': {
#       return dv.getUint16(0)
#     }
#
#     case 'int32': {
#       return dv.getInt32(0)
#     }
#
#     case 'uint32': {
#       return dv.getInt32(0)
#     }
#
#     case 'int64': {
#       return dv.getBigInt64(0)
#     }
#
#     case 'uint64': {
#       return dv.getBigUint64(0)
#     }
#
#     case 'float32': {
#       return dv.getFloat32(0)
#     }
#
#     case 'float64': {
#       return dv.getFloat64(0)
#     }
#
#     case 'string': {
#       return bufferToString(buffer)
#     }
#
#     default:
#       return bufferToHex(buffer).toUpperCase()
#   }
# }


""""
 *
 * @param items [{key: number|string, key_name: string, value_type: string}]
"""
def validateSchema(items):
  if not isinstance(items,list):
    raise ("schema items is not array")


  def validateRequiredProperty(item, key, types):
    prop = item[key]
    if not prop:
      raise ('schema items contains item which has Unset key[${key}]')


    propType = type(prop)
    if types.find(propType) < 0:
      raise ('schema items contains item which has wrong key[${key}] type: ${propType}')



  keys = []

  for i in items:
    item = items[i]
    if item == None:
      raise ("schema items contains null item")

    if type(item).__name__ != "dict":
      raise ("schema items contains none object item")


    validateRequiredProperty(item, 'key', ['number', 'string'])
    key = item.key
    if keys.find(key) >= 0:
      raise ('schema items contains duplicate key[${key}]')

    keys.append(key)

    validateRequiredProperty(item, 'key_name', ['string'])
    validateRequiredProperty(item, 'value_type', ['string'])



def getValueType(key, schema):
  if not isinstance(schema,list):
    return

  for i in schema:
    item = schema[i]
    if type(item).__name__ != 'dict':
      raise ("invalid schema")

    if item['key'] == key:
      return item['value_type']



def getKeyName(key, schema):
  if not isinstance(schema,list):
    return


  for i in schema:
    item = schema[i]
    if type(item).__name__ != 'dict':
      raise ("invalid schema")

    if item['key'] == key:
      return item['key_name']




UNPACK_RESULT_CODE_EMPTY_BUF = 1
UNPACK_RESULT_CODE_DECODE_LENGTH_FAIL = -1
UNPACK_RESULT_CODE_BUF_NOT_ENOUGH = -2
UNPACK_RESULT_CODE_WRONG_KEY_SIZE = -3

class KV():
  def __init__(self,key, value):
    self._key = ensureBuffer(key)
    self._value = ensureBuffer(value)
    self._isStringKey = isString(key)



  def get(self):
    return {'_key':self._key,'_value':self._value,'_isStringKey':self._isStringKey}



  def _checkKey(key):
    if not isinstance(key,str) and not isinstance(key,int):
      raise ("key is not string or number")




  def pack(self):
    keyLength = len(self._key)
    totalLength = 1 + keyLength + len(self._value)
    lengthBuffer = encodeLength(totalLength)
    lengthBufferSize = len(lengthBuffer)
    finalLength = lengthBufferSize + totalLength

    keyLengthByte = keyLength & 0x7F
    if self._isStringKey:
      keyLengthByte = keyLengthByte | 0x80

    buffer = [0 for i in range(0,finalLength)]
    for i in range(len(lengthBuffer)):
      buffer[i] = lengthBuffer[i]
    buffer[lengthBufferSize] = keyLengthByte

    buffer[lengthBufferSize + 1] = self._key[0]
    x = lengthBufferSize + 1 + keyLength
    for i in self._value:
      buffer[x] = i
      x += 1
    return buffer

  @staticmethod
  def unpack(buffer):
    if not buffer or len(buffer) == 0:
      return {'code': UNPACK_RESULT_CODE_EMPTY_BUF, 'kv': None, 'pendingParseBuffer': buffer}

    dlr = decodeLength(buffer)
    if dlr['code'] != 0:
      return {'code': UNPACK_RESULT_CODE_DECODE_LENGTH_FAIL, 'kv': None, 'pendingParseBuffer': None}

    payloadLength = dlr['length']


    remainingLength = len(buffer) - dlr['lengthByteSize']- payloadLength
    if remainingLength < 0 or (len(buffer) - dlr['lengthByteSize']) < 0:
      return {'code': UNPACK_RESULT_CODE_BUF_NOT_ENOUGH, 'kv': None, 'pendingParseBuffer': buffer}

    payload = buffer[dlr['lengthByteSize']:dlr['lengthByteSize'] + dlr['length']]
    if len(payload) == 0:
      return {'code': UNPACK_RESULT_CODE_BUF_NOT_ENOUGH, 'kv': None, 'pendingParseBuffer': buffer}

    isStringKey = False
    keySizeByte = payload[0]
    keyLength = keySizeByte & 0x7F
    if (keySizeByte & 0x80) != 0:
      isStringKey = True

    valueLength = len(payload) - 1 - keyLength
    if valueLength < 0:
      return {'code': UNPACK_RESULT_CODE_WRONG_KEY_SIZE, 'kv': None, 'pendingParseBuffer': buffer}


    keyBuffer = payload[1:1 + keyLength]
    key = bufferToString(keyBuffer) if isStringKey else decodeNumber(keyBuffer)
    valueBuffer = payload[1 + keyLength:]

    kv = KV(key, valueBuffer)
    kv = kv.get()

    return {
      'code': 0,
      'kv': kv,
      'pendingParseBuffer': buffer[dlr['lengthByteSize'] + dlr['length']:]
    }


  def isStringKey(self):
    return self._isStringKey


  def key(self):
    return tbufferToString(self._key) if self._isStringKey else decodeNumber(self._key)


  def keyLength(self):
    return self._key.length


  def value(self):
    return self._value


  def stringValue(self):
    return bufferToString(self._value)


  def numberValue(self):
    return decodeNumber(self._value)




class BKV():
  def __init__(self):
    self._kvs = []


  def pack(self,key,value):
    if len(self._kvs) == 0:
      return []

    buffer = []

    for i in self._kvs:
      kv = KV(key,value)
      buffer = concatenateBuffer(buffer, kv.pack())
    return buffer

  @staticmethod
  def unpack(buffer):
    bkv = BKV()
    while True:
      pr = KV.unpack(buffer)
      if (pr['code'] == 0):
        if (pr['kv'] != None):
          a = bkv.add(pr['kv'])
        buffer = pr['pendingParseBuffer']
      else :
        if (pr['code'] == UNPACK_RESULT_CODE_EMPTY_BUF):
          break
        else :
          return {'code': pr['code'], 'bkv': None, 'pendingParseBuffer': pr['pendingParseBuffer']}
    return {'code': 0, 'bkv': a, 'pendingParseBuffer':None}



  def items(self):
    return self._kvs


  def add(self,kv):

    self._kvs.append(kv)
    return {'_kvs':self._kvs}



  def addByStringKey(self,key, value):
    self.add(KV(key, value))


  def addByNumberKey(self,key, value):
    self.add(KV(key, value))

  def getStringValue(self,key):
    for k in self._kvs:
      kv = self._kvs[k]
      if (kv.key() == key):
        return kv.stringValue()

  def getNumberValue(self,key):
    for k in self._kvs:
      kv = self._kvs[k]
      if kv.key() == key:
        return kv.numberValue()


  def containsKey(self,key):
    flag = False
    for k in self._kvs:
      kv = self._kvs[k]
      if kv.key() == key:
        flag = True
        break

    return flag


  def get(self,key):
    for k in self._kvs:
      kv = self._kvs[k]
      if kv.key() == key:
        return kv.value()


  def parse(self,key, schema):
    valueType = getValueType(key, schema)
    value = self.get(key)
    if not value:
      return

    return parseBuffer(value, valueType)

  def dump(self):
    for i in self._kvs:
      kv = self._kvs[i]
      valueString = bufferToHex(kv.value())
      valueFirstByte = kv.value()[0]
      if (0x20 <= valueFirstByte & valueFirstByte <= 0x7E):
        valueString += " (s: " + bufferToString(kv.value()) + ")"

      if kv.isStringKey():
       print("[BKV] key[s]: %s -> value[%d]: %s ", kv.key(), kv.value().length, valueString)
      else:
        print("[BKV] key[n]: %s -> value[%d]: %s ", kv.key().toString(16), kv.value().length, valueString)


# bkv = {
#   BKV: BKV,
#   KV: KV,
#   bufferToHex: bufferToHex,
#   hexToBuffer: hexToBuffer,
#   concatenateBuffer: concatenateBuffer,
#   stringToBuffer: stringToBuffer,
#   validateSchema: validateSchema,
#   getKeyName: getKeyName,
#   getValueType: getValueType,
#   # parseBuffer: parseBuffer,
# }


def unpack(str):
  Bkv = BKV()
  a = hexToBuffer(str)
  result = Bkv.unpack(a)
  data = []
  # try:
  bkv = result['bkv']['_kvs']
  for item in bkv:
    rawKey = item['_key'][0]
    key = rawKey
    if not item['_isStringKey']:
      key = hex(key)
    valueType = getValueType(rawKey, None)
    value = bufferToHex(item['_value']).replace('x','0').upper()
    key_name = getKeyName(rawKey, None)
    data.append({
      'key': key,
      'value': value,
    })
  # except:
  #   pass
  return data




def pack(item):
  Bkv = BKV()
  item['kv'] = ''
  key = int(item['key'], 16)
  value = item['value']
  value = hexToBuffer(value)
  kv = KV(key, value)
  kvalue = kv.get()
  hev = kv.pack()
  item['kv'] = bufferToHex(hev).replace('x', '0')
  resp = Bkv.add(kvalue)
  bkv = bufferToHex(Bkv.pack(key, value)).replace('x', '0')
  return bkv


if __name__ == '__main__':
  # resp = unpack('04010110010a0102000000000000000008010361006290000109010447562e347234340301051a1601483839383630343136313431383731383939313039')
  resp = unpack('04010110170a010200000000000000000901038223081100185965019403014a0104013e0000030107000301960028015b030108000301090004010a0000040195000004010b000004010c000004010d000004010e000028015b030108010301090004010a0000040195000004010b000004010c000004010d000004010e0000')

  print(resp)

  # 命令
  # key_cmd = resp[0]['key']
  key_cmd = '040101'
  value_cmd = resp[0]['value']
  # 帧流水号
  # key_framenumber = resp[1]['key']
  key_framenumber = '0a0102'
  value_framenumber = resp[1]['value']
  # 设备mac
  # key_mac = resp[2]['key']
  key_mac = '080103'
  value_mac = resp[2]['value']
  # x06
  key_version = '090106'
  # key_version = '0x6'
  value_version = '20200826201437'
  redata = key_cmd+value_cmd+key_framenumber+value_framenumber+key_mac+value_mac+key_version+value_version
  print(redata)
  print(len(redata))





if __name__ == '__main__':
    # Bkv = BKV()
    #
    # # item = itemList[0]
    # item = itemList[1]
    #
    # item['kv'] = ''
    # key = int(item['key'], 16)
    # value = item['value']
    # value = hexToBuffer(value)
    # kv = KV(key, value)
    # kvalue = kv.get()
    # hev = kv.pack()
    # item['kv'] = bufferToHex(hev).replace('x', '0')
    # resp = Bkv.add(kvalue)
    # bkv = bufferToHex(Bkv.pack(key, value)).replace('x', '0')
    # a = bufferToHex(Bkv.pack(key, value)).replace('x', '0')
    # print(a)
    itemList = [{'key': '0x1', 'value': '1007'}, {'key': '0x2', 'value': '00000000000189A8'},
                {'key': '0x3', 'value': '610062900001'},{'key': '0x8', 'value': '03'},
                {'key': '0x13', 'value': '01'},{'key': '0x12', 'value': '01'},
                {'key': '0x47', 'value': '01'},{'key': '0x14', 'value': '01E0'}]
    redata = ''
    for i in itemList:
      resp = pack(i)
      print(resp)
      redata += resp
    print(redata)





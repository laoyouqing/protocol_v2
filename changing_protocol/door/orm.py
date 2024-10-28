#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'Waylin'

import asyncio
import logging

import pymysql



configs = {
    'debug': True,
    'db': {
        'host': '60.204.222.113',
        'port': 3306,
        'user': 'root',
        'password': 'Qf123456',
        'db': 'qf_change'
    },
}



def log(sql, args=()):
    logging.info('SQL: %s' % sql)

def select(sql, args, size=None):
    # log(sql, args)
    # print(sql,args)
    conn = pymysql.connect(**configs['db'])
    # with (__pool) as conn:
    cur = conn.cursor(pymysql.cursors.DictCursor)
    cur.execute(sql.replace('?', '%s'), args or ())
    if size:
        rs = cur.fetchmany(size)
    else:
        rs = cur.fetchall()
    cur.close()
    conn.close()
    logging.info('rows returned: %s' % len(rs))
    return rs

def execute(sql, args, autocommit=True):
    conn = pymysql.connect(**configs['db'])
    if not autocommit:
        conn.begin()
    try:
        cur = conn.cursor()
        cur.execute(sql.replace('?', '%s'), args)
        affected = cur.rowcount
        conn.commit()
        cur.close()
        # if not autocommit:
        conn.close()
    except BaseException as e:
        if not autocommit:
            conn.rollback()
        raise
    return affected



def insert(table_name, field_name, field_value):
    conn = pymysql.connect(**configs['db'])  # 获取连接对象
    cr_obj = conn.cursor()  # 获取cursor对象
    sql = "insert into {} ({}) values ({})".format(table_name, field_name, field_value)
    ret = cr_obj.execute(sql)
    conn.commit()
    cr_obj.close()
    conn.close()


def create_args_string(num):
    L = []
    for n in range(num):
        L.append('?')
    return ', '.join(L)


class Field(object):

    def __init__(self, name, column_type, primary_key, default):
        self.name = name
        self.column_type = column_type
        self.primary_key = primary_key
        self.default = default

    def __str__(self):
        return '<%s, %s:%s>' % (self.__class__.__name__, self.column_type, self.name)


class Fieldecimal(object):

    def __init__(self, name, column_type, primary_key, default):
        self.name = name
        self.column_type = column_type
        self.primary_key = primary_key
        self.default = default

    def __str__(self):
        return '<%s, %s:%s>' % (self.__class__.__name__, self.column_type, self.name)


class StringField(Field):

    def __init__(self, name=None, primary_key=False, default='', ddl='varchar(100)'):
        super().__init__(name, ddl, primary_key, default)


class BooleanField(Field):

    def __init__(self, name=None, default=False):
        super().__init__(name, 'boolean', False, default)


class IntegerField(Field):

    def __init__(self, name=None, primary_key=False, default=0):
        super().__init__(name, 'bigint', primary_key, default)


class TinyintField(Field):

    def __init__(self, name=None, primary_key=False, default=0):
        super().__init__(name, 'tinyint', primary_key, default)


class FloatField(Field):

    def __init__(self, name=None, primary_key=False, default=0.0):
        super().__init__(name, 'float', primary_key, default)


class DecimalField(Field):
    def __init__(self, name=None, primary_key=False, default=0.00):
        super().__init__(name, 'decimal', primary_key, default)


class DateField(Field):

    def __init__(self, name=None, primary_key=False, default=0):
        super().__init__(name, 'date', primary_key, default)


class DatetimeField(Field):

    def __init__(self, name=None, primary_key=False, default=0):
        super().__init__(name, 'datetime', primary_key, default)


class TextField(Field):

    def __init__(self, name=None, default=None):
        super().__init__(name, 'longtext', False, default)


class ModelMetaclass(type):

    def __new__(cls, name, bases, attrs):
        if name == 'Model':
            return type.__new__(cls, name, bases, attrs)
        tableName = attrs.get('__table__', None) or name
        logging.info('found model: %s (table: %s)' % (name, tableName))
        mappings = dict()
        fields = []
        primaryKey = None
        for k, v in attrs.items():
            if isinstance(v, Field):
                logging.info('  found mapping: %s ==> %s' % (k, v))
                mappings[k] = v
                if v.primary_key:
                    # 找到主键:
                    if primaryKey:
                        raise Exception('Duplicate primary key for field: %s' % k)
                    primaryKey = k
                else:
                    fields.append(k)
        if not primaryKey:
            raise Exception('Primary key not found.')
        for k in mappings.keys():
            attrs.pop(k)
        escaped_fields = list(map(lambda f: '`%s`' % f, fields))
        attrs['__mappings__'] = mappings  # 保存属性和列的映射关系
        attrs['__table__'] = tableName
        attrs['__primary_key__'] = primaryKey  # 主键属性名
        attrs['__fields__'] = fields  # 除主键外的属性名
        attrs['__select__'] = 'select `%s`, %s from `%s`' % (primaryKey, ', '.join(escaped_fields), tableName)
        attrs['__insert__'] = 'insert into `%s` (%s, `%s`) values (%s)' % (
            tableName, ', '.join(escaped_fields), primaryKey, create_args_string(len(escaped_fields) + 1))
        attrs['__update__'] = 'update `%s` set %s where `%s`=?' % (
            tableName, ', '.join(map(lambda f: '`%s`=?' % (mappings.get(f).name or f), fields)), primaryKey)
        attrs['__delete__'] = 'delete from `%s` where `%s`=?' % (tableName, primaryKey)
        return type.__new__(cls, name, bases, attrs)


class Model(dict, metaclass=ModelMetaclass):

    def __init__(self, **kw):
        super(Model, self).__init__(**kw)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(r"'Model' object has no attribute '%s'" % key)

    def __setattr__(self, key, value):
        self[key] = value

    def getValue(self, key):
        return getattr(self, key, None)

    def getValueOrDefault(self, key):
        value = getattr(self, key, None)
        if value is None:
            field = self.__mappings__[key]
            if field.default is not None:
                value = field.default() if callable(field.default) else field.default
                logging.debug('using default value for %s: %s' % (key, str(value)))
                setattr(self, key, value)
        return value

    @classmethod
    def findAll(cls, where=None, args=None, **kw):
        ' find objects by where clause. '
        sql = [cls.__select__]
        if where:
            sql.append('where')
            sql.append(where)
            # print(sql)
        if args is None:
            args = []
        orderBy = kw.get('orderBy', None)
        if orderBy:
            sql.append('order by')
            sql.append(orderBy)
        limit = kw.get('limit', None)
        if limit is not None:
            sql.append('limit')
            if isinstance(limit, int):
                sql.append('?')
                args.append(limit)
            elif isinstance(limit, tuple) and len(limit) == 2:
                sql.append('?, ?')
                args.extend(limit)
            else:
                raise ValueError('Invalid limit value: %s' % str(limit))
        rs = select(' '.join(sql), args)
        return [cls(**r) for r in rs]

    @classmethod
    def totalTable(cls, selectField, where=None, group=None, args=None):
        ' find number by select and where. '
        sql = ['select %s from `%s`' % (selectField, cls.__table__)]
        if where:
            sql.append('where')
            sql.append(where)
        if group:
            sql.append('group by')
            sql.append(group)
        rs = select(' '.join(sql), args)
        if len(rs) == 0:
            return None
        return [cls(**r) for r in rs]

    @classmethod
    def findNumber(cls, selectField, where=None, args=None):
        ' find number by select and where. '
        sql = ['select %s _num_ from `%s`' % (selectField, cls.__table__)]
        # print(sql)
        if where:
            sql.append('where')
            sql.append(where)
        rs = select(' '.join(sql), args, 1)
        if len(rs) == 0:
            return None
        return rs[0]['_num_']

    @classmethod
    def find(cls, pk):
        ' find object by primary key. '
        rs = select('%s where `%s`=?' % (cls.__select__, cls.__primary_key__), [pk], 1)
        if len(rs) == 0:
            return None
        return cls(**rs[0])


    def save(self):
        args = list(map(self.getValueOrDefault, self.__fields__))
        args.append(self.getValueOrDefault(self.__primary_key__))
        rows = execute(self.__insert__, args)
        # print(rows)
        if rows != 1:
            logging.warn('failed to insert record: affected rows: %s' % rows)


    def update(self):
        args = list(map(self.getValue, self.__fields__))
        args.append(self.getValue(self.__primary_key__))
        rows = execute(self.__update__, args)
        if rows != 1:
            logging.warn('failed to update by primary key: affected rows: %s' % rows)


    def remove(self):
        args = [self.getValue(self.__primary_key__)]
        rows = execute(self.__delete__, args)
        if rows != 1:
            logging.warn('failed to remove by primary key: affected rows: %s' % rows)






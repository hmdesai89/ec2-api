from oslo_config import cfg
from oslo_log import log as logging
from ec2api.api import clients
from ec2api.api import common
from ec2api.api import ec2utils
from datetime import datetime
from ec2api import exception
from ec2api.i18n import _
import urllib2
import pytz
import json
import base64
import ast

field = '{"end_time": "%s" , "select_fields": ["vrouter", "sourcevn", "sourceip", "destvn", "destip", "protocol", "sport", "dport",  "direction_ing", "setup_time", "teardown_time","agg-packets", "agg-bytes", "action", "sg_rule_uuid", "nw_ace_uuid",  "underlay_proto","underlay_source_port","UuidKey"], "start_time": "%s" , "table": "FlowRecordTable",'

Validator = common.Validator
admin_group = cfg.OptGroup(name='admin_account',
                                title='admin group ')
accounts = [ 
            cfg.StrOpt('account_id',
                                help=('admin account Id')),
            cfg.StrOpt('password',
                                help=('password for admin account Id')),
            cfg.StrOpt('query_url',
                                help=('url of analytics query service'))
]

CONF = cfg.CONF
CONF.register_group(admin_group)
CONF.register_opts(accounts, admin_group)

def isInrange(start_time,end_time):
    s_d = datetime.strptime(start_time, '%d-%m-%Y %H:%M:%S')
    e_d = datetime.strptime(end_time, '%d-%m-%Y %H:%M:%S')
    delta= int((e_d - s_d).total_seconds())
    if delta <= 3600:
        return True
    else:
        return False

def convert_to_now(time):
    current_time= datetime.now()
    print "*******", time
    t_time= datetime.strptime(time, '%d-%m-%Y %H:%M:%S')
    local = pytz.timezone ("Asia/Kolkata")
    local_dt = local.localize(t_time, is_dst=None)
    utc_dt = local_dt.astimezone (pytz.utc)
    utcdt = utc_dt.replace(tzinfo=None)
    delta=int( (current_time - utcdt).total_seconds())
    now_time= 'now-%ss' % (delta)
    return now_time

#validate admin password
def validate_admin_account(account_id,password,m_id,m_pass):
    CONF(default_config_files=['/etc/ec2api/ec2api.conf'])
    if (m_id == account_id) and (base64.b64decode(m_pass) == password):
        return True;
    elif CONF.admin_account.account_id != account_id:
        raise exception.AuthFailure("Authorization failed, Not authorise")
    else:
        return False;

#Flow Log API
def describe_flow_log(context,start_time,end_time,account_id=None,admin_password=None):
    CONF(default_config_files=['/etc/ec2api/ec2api.conf'])
    url = CONF.admin_account.query_url
    if not isInrange(start_time,end_time):
        raise exception.TimeRangeError(reason='Difference between start and end time must be less than 1 hour')
    start_time= convert_to_now(start_time)
    end_time= convert_to_now(end_time)
    account_id_match = CONF.admin_account.account_id
    admin_password_match = CONF.admin_account.password
    if admin_password is None and account_id:
	raise exception.PasswordMissing(reason='admin password must be required')
    if admin_password:
        if not validate_admin_account(context.project_id,admin_password,account_id_match,admin_password_match):
	    raise exception.AuthFailure(reason='Authorization failed, password incorrect. Please enter a valid admin password')
	#if only account id non for admin show flow log for all account
        if admin_password and account_id is None:
            data = field + '"end_time": "%s" , "start_time": "%s"}' % (end_time, start_time)
        if admin_password and account_id:
            account_id= account_id.split('-')[1]
            data = field + '"end_time": "%s" , "start_time": "%s", "where": [[{"name": "sourcevn", "value": "default-domain:Customer-%s:default-virtual-network", "op": 1}]] }' % (end_time, start_time,account_id)
    else  :
        data = field + '"end_time": "%s" , "start_time": "%s", "where": [[{"name": "sourcevn", "value": "default-domain:Customer-%s:default-virtual-network", "op": 1}]] }' % (end_time, start_time,context.project_id)
    req = urllib2.Request(url, data, {'Content-Type': 'application/json'})
    try:
        f = urllib2.urlopen(req,timeout=600)
    except urllib2.HTTPError as err:
        raise exception.ConnectionError(reason=err)
    return json.load(f)

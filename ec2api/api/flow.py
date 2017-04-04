from oslo_config import cfg
from oslo_log import log as logging
from ec2api.api import clients
from ec2api.api import common
from ec2api.api import ec2utils
from datetime import datetime
from ec2api import exception
from ec2api.i18n import _
from ec2api.db import api as db_api
import urllib2
import pytz
import json
import base64
import ast
import random

field = ('{"limit": 100000, "select_fields": ['
           '"sourcevn", "sourceip", "destvn", "destip", "protocol", '
           '"sport", "dport",  "direction_ing", "setup_time", '
           '"teardown_time","agg-packets", "agg-bytes", "action", '
           '"sg_rule_uuid",  "underlay_proto", '
           '"underlay_source_port"],'
           '"table": "FlowRecordTable",')

Validator = common.Validator
admin_group = cfg.OptGroup(name='admin_account',
                                title='admin group ')
accounts = [ 
            cfg.StrOpt('account_id',
                                help=('admin account Id')),
            cfg.StrOpt('password',
                                help=('password for admin account Id')),
            cfg.StrOpt('query_url',
                                help=('url of analytics query service')),
            cfg.IntOpt('day_limit',
                                help=('start_time and end_time period limit')),
            cfg.IntOpt('time_limit',
                                help=('start_time and end_time period limit'))
]

CONF = cfg.CONF
CONF.register_group(admin_group)
CONF.register_opts(accounts, admin_group)

def isInrange(start_time,end_time,time_limit):
    s_d = datetime.strptime(start_time, '%d-%m-%Y %H:%M:%S')
    e_d = datetime.strptime(end_time, '%d-%m-%Y %H:%M:%S')
    delta= int((e_d - s_d).total_seconds())
    if delta <= 0:
        raise exception.TimeRangeError(reason="Invalid input. End time must be greater than start time")
    if delta <= time_limit:
        return True
    else:
        return False

def convert_to_now(time,day_limit):
    current_time= datetime.now()
    t_time= datetime.strptime(time, '%d-%m-%Y %H:%M:%S')
    local = pytz.timezone ("Asia/Kolkata")
    local_dt = local.localize(t_time, is_dst=None)
    utc_dt = local_dt.astimezone (pytz.utc)
    utcdt = utc_dt.replace(tzinfo=None)
    delta=int( (current_time - utcdt).total_seconds())
    if delta >= day_limit:
        num_days_limit = day_limit/(60*60*24)
        raise exception.TimeRangeError(reason=("Invalid input. Time period between Current time and start_time or "
                                              "end_time should not be greater than %sdays") % num_days_limit)
    now_time= 'now-%ss' % (delta)
    return now_time

#validate admin password
def validate_admin_account(account_id,password,m_id,m_pass):
    CONF(default_config_files=['/etc/ec2api/ec2api.conf'])
    if ( account_id in m_id) and (base64.b64decode(m_pass) == password):
        return True;
    elif CONF.admin_account.account_id != account_id:
        raise exception.AuthFailureError("Authorization failed, Not authorise")
    else:
        return False;

#Flow Log API
def describe_flow_logs(context,start_time,end_time,account_id=None,admin_password=None,direction_ing=None):
    CONF(default_config_files=['/etc/ec2api/ec2api.conf'])
    url = CONF.admin_account.query_url
    day_limit = CONF.admin_account.day_limit
    time_limit = CONF.admin_account.time_limit
    if not isInrange(start_time,end_time,time_limit):
        num_min_limit = time_limit/(60)
        raise exception.TimeRangeError(reason=('Difference between start and end time '
                                              'should not be greater than %s minutes') % num_min_limit)
    start_time= convert_to_now(start_time,day_limit)
    end_time= convert_to_now(end_time,day_limit)
    account_id_match = CONF.admin_account.account_id.split()
    admin_password_match = CONF.admin_account.password
    if direction_ing is not None:
        if direction_ing == 0:
            name='destvn'
        elif direction_ing == 1:
            name = 'sourcevn'
        else:
            raise exception.ValidationError(reason="direction_ing value is invalid. Please enter "
                                                   "direction_ing 0 for egress traffic and 1 for ingress traffic")
    if admin_password is None and account_id:
	raise exception.AuthFailureError(reason='Authorization failed, password missing. '
                                                'Please enter a valid admin password')
    if admin_password:
        if not validate_admin_account(context.project_id,admin_password,account_id_match,admin_password_match):
	    raise exception.AuthFailureError(reason='Authorization failed, password incorrect.'
                                                    ' Please enter a valid admin password')
	#if only account id non for admin show flow log for all account
        if admin_password and account_id is None:
            if direction_ing is not None:
                data = field + '"end_time": "%s" , "start_time": "%s", "dir": %s}' % (end_time, start_time,direction_ing)
            else:
                data = field + '"end_time": "%s" , "start_time": "%s"}' % (end_time, start_time)
        if admin_password and account_id:
            if direction_ing is None:
                raise exception.ValidationError(reason="Parameter direction_ing is missing. Please enter "
                                                       "direction_ing 0 for egress traffic and 1 for ingress traffic")
            account_id= account_id.split('-')[1]
            data = field + ('"end_time": "%s" , "start_time": "%s", "dir": %s, "filter": [[{"name": '
                           '"%s", "value": ".*%s.*", '
                           '"op": 8}]] }') % (end_time, start_time, direction_ing, name, account_id)
    else  :
        if direction_ing is None:
            raise exception.ValidationError(reason="Parameter direction_ing is missing. Please enter "
                                                   "direction_ing 0 for egress traffic and 1 for ingress traffic")
        data = field + ('"end_time": "%s" , "start_time": "%s", "dir": %s, "filter": [[{"name": "%s", '
                        '"value": ".*%s.*", '
                        '"op": 8}]] }') % (end_time, start_time,direction_ing,name,context.project_id)
    req = urllib2.Request(url, data, {'Content-Type': 'application/json'})
    try:
        f = urllib2.urlopen(req,timeout=600)
    except urllib2.HTTPError as err:
        raise exception.ConnectionError(reason=err)
    return json.load(f)


def enable_flow_logs(context,flow_logging):
    random.seed(context.project_id)
    rand = random.randint(1, 0xffffff)
    bucket_name= 'vpc-flow-%s-%s' % (rand, context.project_id[20:])
    flows = db_api.get_items(context, 'flow')
    with common.OnCrashCleaner() as cleaner:
     
        if flow_logging == 1:
            if flows:
                raise exception.AlreadyEnable(reason='Flow_log already enabled')
            enabled_at= datetime.now().strftime('%d-%m-%y %H:%M:%S')
            flow = db_api.add_item(context, 'flow',
                                   {'bucket_name': bucket_name, 'enabled_at': enabled_at})
            cleaner.addCleanup(db_api.delete_item, context, flow['id'])
            return {'Flow_status' : 'enable','bucket_name': bucket_name}
        else:
            if not flows:
                raise exception.AlreadyDisable(reason='Flow_log already disabled')
            flow_id= flows[0]['id']
            db_api.delete_item(context, flow_id)
            cleaner.addCleanup(db_api.restore_item, context, 'flow', flows)
    
            return True

def describe_flow_logs_status(context):
    random.seed(context.project_id)
    rand = random.randint(1, 0xffffff)
    bucket_name= 'vpc-flow-%s-%s' % (rand, context.project_id[20:])
    flows = db_api.get_items(context, 'flow')
    if not flows:
        return  {'bucket_name': bucket_name, 'status': 'Disable'}
    else:
        return {'status' :'Enable','bucket_name': bucket_name}

def describe_flow_log_enable_accounts(context):
    flows = db_api.get_items_project_ids(context, 'flow')
    flow_id = []
    for flow in flows:
        fdata = {'project_id': flow['project_id'], 'bucket_name': flow['data']['bucket_name'], 'enabled_at': flow['data']['enabled_at']}
        flow_id.append(fdata)
    return {'account_ids': flow_id}

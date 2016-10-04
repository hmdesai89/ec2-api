import urllib2
import json
from oslo_config import cfg
from oslo_log import log as logging

from ec2api.api import clients
from ec2api.api import common
from ec2api.api import ec2utils
from ec2api import exception
from ec2api.i18n import _
import urllib2
import json
import base64

Validator = common.Validator
admin_group = cfg.OptGroup(name='admin_account',
                                title='admin group ')
accounts = [ 
            cfg.StrOpt('account_id',
                                help=('admin account Id')),
            cfg.StrOpt('password',
                                help=('password for admin account Id'))
]

CONF = cfg.CONF
CONF.register_group(admin_group)
CONF.register_opts(accounts, admin_group)


#validate admin password
def validate_admin_account(account_id,password):
    CONF(default_config_files=['/etc/ec2api/ec2api.conf'])
    if (CONF.admin_account.account_id == account_id) and (base64.b64decode(CONF.admin_account.password) == password):
        return True;
    else:
        return False;



def describe_flow_log(context,start_time,end_time,account_id=None,admin_password=None):
    #url = 'http://192.168.100.12:8081/analytics/query'
    url = 'http://10.140.214.62:8081/analytics/query'
    if admin_password is None and account_id:
	raise exception.PasswordMissing(reason='admin password must be required')
    if admin_password:
        if not validate_admin_account(context.project_id,admin_password):
	    raise exception.AuthFailure()
	#if only account id non for admin show flow log for all account
        if admin_password and account_id is None:
            data = '{"end_time": "%s" , "select_fields": ["vrouter", "sourcevn", "sourceip", "destvn", "destip", "protocol", "sport", "dport",  "direction_ing", "setup_time", "teardown_time","agg-packets", "agg-bytes", "action", "sg_rule_uuid", "nw_ace_uuid",  "underlay_proto","underlay_source_port", "UuidKey"], "start_time": "%s" , "table": "FlowRecordTable"}' % (end_time, start_time)
	#show log for account_id given by admin
        if admin_password and account_id:
            account_id= account_id.split('-')[1]
            data = '{"end_time": "%s" , "select_fields": ["vrouter", "sourcevn", "sourceip", "destvn", "destip", "protocol", "sport", "dport",  "direction_ing", "setup_time", "teardown_time","agg-packets", "agg-bytes", "action", "sg_rule_uuid", "nw_ace_uuid",  "underlay_proto","underlay_source_port", "UuidKey"], "start_time": "%s" , "table": "FlowRecordTable",  "where": [[{"name": "sourcevn", "value": "default-domain:Customer-%s:default-virtual-network", "op": 1}]] }' % (end_time, start_time,account_id)
    #if admin password and account_id both are none show
    #  flow log for account_id from which flow log requested
    else  :
            data = '{"end_time": "%s" , "select_fields": ["vrouter", "sourcevn", "sourceip", "destvn", "destip", "protocol", "sport", "dport",  "direction_ing", "setup_time", "teardown_time","agg-packets", "agg-bytes", "action", "sg_rule_uuid", "nw_ace_uuid",  "underlay_proto","underlay_source_port", "UuidKey"], "start_time": "%s" , "table": "FlowRecordTable",  "where": [[{"name": "sourcevn", "value": "default-domain:Customer-%s:default-virtual-network", "op": 1}]] }' % (end_time, start_time,context.project_id)
    req = urllib2.Request(url, data, {'Content-Type': 'application/json'})
    try:
        f = urllib2.urlopen(req,timeout=1800)
    except urllib2.HTTPError as err:
        raise exception.ConnectionError(reason=err)
    return json.load(f)
 

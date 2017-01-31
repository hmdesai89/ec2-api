# Copyright 2014
# The Cloudscaling Group, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from neutronclient.common import exceptions as neutron_exception
from oslo_config import cfg
from oslo_log import log as logging


from ec2api.api import validator
from ec2api.db import api as db_api
from ec2api import exception
from ec2api.api import common
from ec2api.api import ec2utils
from ec2api import exception

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


"""Quota related API implementation
"""

Validator = common.Validator

def create_paas_account(context, account_id):


    account_id = account_id[4:]
    ## Who all should be able to create an pass account
    account = context.project_id
    
    ## We need project-i&*d equal to  tenant-id
    ## changing context.project id
    dummy_context = context    
    dummy_context.project_id = account_id

    with common.OnCrashCleaner() as cleaner:
        ## Check if an PASS account for this tenant already exist
        pass_acc = next((i for i in db_api.get_items(dummy_context, 'paas')
                     if i['os_id'] == account_id), None)
        
        if pass_acc :
           raise exception.PassAccountAleradyExisting() 
       
       
        os_id = ec2utils.convert_to_os_id(account_id)
        db_api.add_item_id(context, 'paas', os_id, project_id=account_id)      
        return {'paas-account': _format_pass_account(context, account, 'Enable' )}

def delete_paas_account(context, account_id):
 
    account_id = account_id[4:]
    dummy_context = context  
    dummy_context.project_id = account_id
      
    paas_acc = ec2utils.get_db_items(context, 'paas')
    paas_acc = paas_acc[0]

    ## We need project-id equal to  tenant-id
    ## changing context.project id

    
    pni = db_api.get_items(dummy_context, 'pni', None)
    
    
    if pni :
        msg = _("The PASS account '%(account_id)' has dependencies and "
                "cannot be deleted.")
        msg = msg % {'account_id': account_id}
        raise exception.DependencyViolation(msg)
     
    db_api.delete_item(dummy_context, paas_acc[id])    
    return True

def _format_pass_account(context,account, status):

    return {
        'acc-id' : account,
        'pass' : status
    }


class PASSDescriber(common.TaggableItemsDescriber,
                   common.NonOpenstackItemsDescriber):

    KIND = 'paas'
    FILTER_MAP = {'pass-acc': 'accountId',
                  }

    def format(self, item=None, os_item=None):
        return _format_pass_account(item)


def describe_paas_account(context, pass_id=None, filter=None):
    formatted_pass = PASSDescriber().describe(
        context, ids=pass_id, filter=filter)
    return {'paasSet': formatted_pass}




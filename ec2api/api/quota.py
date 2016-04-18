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

from ec2api.api import clients
from ec2api.api import common
from ec2api.api import ec2utils
from ec2api import exception
from ec2api.i18n import _


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


"""Quota related API implementation
"""

Validator = common.Validator

def update_quota(context, account, resource, quota):

    account = account[4:]

    neutron = clients.neutron(context)
    with common.OnCrashCleaner() as cleaner:

        os_quota_body = {
                          'quota': {
                                     resource : quota,
                                   }
                        }

        os_quota = neutron.update_quota(account, os_quota_body)['quota']

        return {'quota-update': _format_quota_update(context, resource, os_quota)}

def _format_quota_update(context, resource, os_quota):

    return {
       resource : os_quota[resource]
    }

def show_quota(context, account):

    account = account[4:]

    neutron = clients.neutron(context)
    with common.OnCrashCleaner() as cleaner:

        os_quota = neutron.show_quota(account)

        return {'show-quota': _format_show_quota(context, os_quota)}

def _format_show_quota(context, os_quota):

    return {
       'Networks': os_quota['quota']['network'],
       'Subnets': os_quota['quota']['subnet'],
       'Ports': os_quota['quota']['port'],
       'Routers': os_quota['quota']['router'],
       'FloatingIps': os_quota['quota']['floatingip'],
       'SecurityGroups': os_quota['quota']['security_group'],
       'SecurityGroupRules': os_quota['quota']['security_group_rule']
    }

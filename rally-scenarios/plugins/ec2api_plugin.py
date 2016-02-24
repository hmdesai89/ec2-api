#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import functools

from rally.common import log as logging
from rally.plugins.openstack import scenario
from rally.task import atomic

import botocoreclient

LOG = logging.getLogger(__name__)


_count_args = dict()


class ActionTimerWithoutFirst(atomic.ActionTimer):

    def __init__(self, scenario_instance, name):
        super(ActionTimerWithoutFirst, self).__init__(scenario_instance, name)
        self.scenario_instance = scenario_instance
        self.name = name

    def __exit__(self, type, value, tb):
        if self.name in _count_args:
            super(ActionTimerWithoutFirst, self).__exit__(type, value, tb)
        else:
            _count_args[self.name] = True


class EC2APIPlugin(scenario.OpenStackScenario):

    def __init__(self, *args, **kwargs):
        super(EC2APIPlugin, self).__init__(*args, **kwargs)
        count_args = dict()

    def _get_client(self, is_nova):
        args = self.context['user']['ec2args']
        client = botocoreclient.get_ec2_client(
            args['url'], args['region'], args['access'], args['secret'])
            #'http://192.168.100.49:8788/services/Cloud','RegionOne','370d11834ecf4211b81888f06e60c5a6','51d2a192511b41bc9d9aa279fb60fdec')
        return client

    def _run_both(self, base_name, func):
        client = self._get_client(False)
        with ActionTimerWithoutFirst(self, base_name + '_ec2api'):
            func(self, client)

    def _run_ec2(self, base_name, func):
        client = self._get_client(False)
        with ActionTimerWithoutFirst(self, base_name + '_ec2api'):
            func(self, client)

    def _runner(run_func):
        def wrap(func):
            @functools.wraps(func)
            def runner(self, *args, **kwargs):
                run_func(self, func.__name__, func)
            return runner
        return wrap

    @scenario.configure()
    @_runner(_run_both)
    def describe_instances(self, client):
        data = client.describe_instances()

    @scenario.configure()
    @_runner(_run_both)
    def describe_addresses(self, client):
        data = client.describe_addresses()

    @scenario.configure()
    @_runner(_run_both)
    def describe_security_groups(self, client):
        data = client.describe_security_groups()

    @scenario.configure()
    @_runner(_run_both)
    def describe_regions(self, client):
        data = client.describe_regions()

    @scenario.configure()
    @_runner(_run_both)
    def describe_images(self, client):
        data = client.describe_images()

    @scenario.configure()
    @_runner(_run_ec2)
    def describe_vpcs(self, client): 
        data = client.describe_vpcs()
        self.assertTrue(True , err_msg="eRROR")

    @scenario.configure()
    @_runner(_run_ec2)
    def describe_subnets(self, client):
        data = client.describe_subnets()

    @scenario.configure()
    @_runner(_run_ec2)
    def describe_network_interfaces(self, client):
        data = client.describe_network_interfaces()

    @scenario.configure()
    @_runner(_run_ec2)
    def describe_route_tables(self, client):
        data = client.describe_route_tables()

    _instance_id_by_client = dict()

    @scenario.configure()
    @_runner(_run_both)
    def describe_one_instance(self, client):
        client_id = str(client._endpoint)
        instance_id = self._instance_id_by_client.get(client_id)
        if not instance_id:
            data = client.describe_instances()
            instances = data['Reservations'][0]['Instances']
            index = len(instances) / 3
            instance_id = instances[index]['InstanceId']
            self._instance_id_by_client[client_id] = instance_id
            LOG.info("found instance = %s for client %s"
                     % (instance_id, client_id))

        data = client.describe_instances(InstanceIds=[instance_id])


    @scenario.configure()
    @_runner(_run_both)
    def create_vpc(self, client, cidr):
        data = client.create_vpc("")



    @scenario.configure()
    def describe_all_in_one(self):
#        self.describe_security_groups()
        self.describe_vpcs()
#        self.describe_subnets()
#        self.describe_network_interfaces()
#        self.describe_route_tables()

    @scenario.configure()
    def describe_networks(self):
        self.describe_vpcs()
        self.describe_subnets()
        self.describe_network_interfaces()
        self.describe_route_tables()

    @scenario.configure()
    def describe_all_vpc_elements(self):
        self.describe_vpcs()
        self.describe_subnets()
        self.describe_network_interfaces()
        self.describe_route_tables()
        self.describe_security_groups()

    @scenario.configure()
    def test_all_vpc_apis_basic(self):
        vpc_id = self.create_vpc("10.0.0.0/16")
        self.describe_vpcs(vpc_id)
        subnet_id = self.create_subnet(vpc_id)
        self.describe_subnet(subnet_id)
        route_table_id = self.create_route_table()
        self.delete_route_table(route_table_id)
        security_group_id = self.create_security_group()
        self.authorize_security_group()
        self.revoke_security_group()
        self.delete_security_group(security_group_id)
        self.allocate_address()
        self.release_address()
        self.delete_subnet(subnet_id)
        self.delete_vpc(vpc_id)
     

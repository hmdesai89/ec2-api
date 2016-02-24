# Copyright 2014 OpenStack Foundation
# All Rights Reserved.
#
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


import testtools
import functools

from rally.common import log as logging
from rally.plugins.openstack import scenario
from rally.task import atomic

import botocoreclient

LOG = logging.getLogger(__name__)
import base
#from ec2api.tests.functional import config

#CONF = config.CONF

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




#import testtools

#from ec2api.tests.functional import base
#from ec2api.tests.functional import config

#CONF = config.CONF


class VPCTest(scenario.OpenStackScenario, base.EC2TestCase):

    @classmethod
    @base.safe_setup
    def setUpClass(cls):
        super(VPCTest, cls).setUpClass()
        if not base.TesterStateHolder().get_vpc_enabled():
            raise cls.skipException('VPC is disabled')

    def __init__(self, *args, **kwargs):
        super(VPCTest, self).__init__(*args, **kwargs)
        count_args = dict()
        self._resource_trash_bin = {}
        self._sequence = -1
    
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
    def test_create_delete_vpc(self,client):
        cidr = '10.1.0.0/16'
        data = client.create_vpc(CidrBlock=cidr)
        vpc_id = data['Vpc']['VpcId']
        dv_clean = self.addResourceCleanUp(client.delete_vpc,
                                           VpcId=vpc_id)

        self.assertEqual(cidr, data['Vpc']['CidrBlock'])
        #if CONF.aws.run_incompatible_tests:
            # NOTE(andrey-mp): not ready
        #    self.assertEqual('default', data['Vpc']['InstanceTenancy'])
        self.assertIsNotNone(data['Vpc'].get('DhcpOptionsId'))

        self.get_vpc_waiter(client).wait_available(vpc_id)

        client.delete_vpc(VpcId=vpc_id)
        self.cancelResourceCleanUp(dv_clean)
        self.get_vpc_waiter(client).wait_delete(vpc_id)

        self.assertRaises('InvalidVpcID.NotFound',
                          client.describe_vpcs,
                          VpcIds=[vpc_id])

        self.assertRaises('InvalidVpcID.NotFound',
                          client.delete_vpc,
                          VpcId=vpc_id)

    @scenario.configure()
    @_runner(_run_both)
    def test_create_more_than_one_vpc(self,client):
        cidr = '10.0.0.0/16'
        data = client.create_vpc(CidrBlock=cidr)
        vpc_id1 = data['Vpc']['VpcId']
        rc1 = self.addResourceCleanUp(client.delete_vpc, VpcId=vpc_id1)
        self.get_vpc_waiter(client).wait_available(vpc_id1)

        cidr = '10.1.0.0/16'
        data = client.create_vpc(CidrBlock=cidr)
        vpc_id2 = data['Vpc']['VpcId']
        rc2 = self.addResourceCleanUp(client.delete_vpc, VpcId=vpc_id2)
        self.get_vpc_waiter(client).wait_available(vpc_id2)

        client.delete_vpc(VpcId=vpc_id1)
        self.cancelResourceCleanUp(rc1)
        self.get_vpc_waiter(client).wait_delete(vpc_id1)

        client.delete_vpc(VpcId=vpc_id2)
        self.cancelResourceCleanUp(rc2)
        self.get_vpc_waiter(client).wait_delete(vpc_id2)


    @scenario.configure()
    @_runner(_run_both)
    def test_describe_vpcs_base(self,client):
        cidr = '10.1.0.0/16'
        data = client.create_vpc(CidrBlock=cidr)
        vpc_id = data['Vpc']['VpcId']
        dv_clean = self.addResourceCleanUp(client.delete_vpc,
                                           VpcId=vpc_id)
        self.get_vpc_waiter(client).wait_available(vpc_id)

        # NOTE(andrey-mp): by real id
        data = client.describe_vpcs(VpcIds=[vpc_id])
        self.assertEqual(1, len(data['Vpcs']))

        # NOTE(andrey-mp): by fake id
        self.assertRaises('InvalidVpcID.NotFound',
                          client.describe_vpcs,
                          VpcIds=['vpc-0'])

        client.delete_vpc(VpcId=vpc_id)
        self.cancelResourceCleanUp(dv_clean)
        self.get_vpc_waiter(client).wait_delete(vpc_id)

    @scenario.configure()
    @_runner(_run_both)
    def test_describe_vpcs_filters(self,client):
        cidr = '10.163.0.0/16'
        data = client.create_vpc(CidrBlock=cidr)
        vpc_id = data['Vpc']['VpcId']
        dv_clean = self.addResourceCleanUp(client.delete_vpc,
                                           VpcId=vpc_id)
        self.get_vpc_waiter(client).wait_available(vpc_id)

        # NOTE(andrey-mp): by filter real cidr
        data = client.describe_vpcs(
            Filters=[{'Name': 'cidr', 'Values': [cidr]}])
        self.assertEqual(1, len(data['Vpcs']))

        # NOTE(andrey-mp): by filter fake cidr
        data = client.describe_vpcs(
            Filters=[{'Name': 'cidr', 'Values': ['123.0.0.0/16']}])
        self.assertEqual(0, len(data['Vpcs']))

        # NOTE(andrey-mp): by fake filter
        self.assertRaises('InvalidParameterValue',
                          client.describe_vpcs,
                          Filters=[{'Name': 'fake', 'Values': ['fake']}])

        data = client.delete_vpc(VpcId=vpc_id)
        self.cancelResourceCleanUp(dv_clean)
        self.get_vpc_waiter(client).wait_delete(vpc_id)

    @scenario.configure()
    @_runner(_run_both)
    #@testtools.skipUnless(CONF.aws.run_incompatible_tests,
    #    "Invalid request on checking vpc atributes.")
    def test_vpc_attributes(self,client):
        cidr = '10.1.0.0/16'
        data = client.create_vpc(CidrBlock=cidr)
        vpc_id = data['Vpc']['VpcId']
        dv_clean = self.addResourceCleanUp(client.delete_vpc,
                                           VpcId=vpc_id)
        self.get_vpc_waiter(client).wait_available(vpc_id)

        self._check_attribute(vpc_id, 'EnableDnsHostnames',client)
        self._check_attribute(vpc_id, 'EnableDnsSupport',client)

        data = client.delete_vpc(VpcId=vpc_id)
        self.cancelResourceCleanUp(dv_clean)
        self.get_vpc_waiter(client).wait_delete(vpc_id)

    def _check_attribute(self, vpc_id, attribute,client):
        req_attr = attribute[0].lower() + attribute[1:]
        data = client.describe_vpc_attribute(VpcId=vpc_id,
                                                  Attribute=req_attr)
        attr = data[attribute].get('Value')
        self.assertIsNotNone(attr)

        kwargs = {'VpcId': vpc_id, attribute: {'Value': not attr}}
        data = client.modify_vpc_attribute(*[], **kwargs)
        data = client.describe_vpc_attribute(VpcId=vpc_id,
                                                  Attribute=req_attr)
        self.assertNotEqual(attr, data[attribute].get('Value'))


    @scenario.configure()
    @_runner(_run_both)
    def test_create_with_invalid_cidr(self,client):
        def _rollback(fn_data):
            client.delete_vpc(VpcId=fn_data['Vpc']['VpcId'])

        # NOTE(andrey-mp): The largest uses a /16 netmask
        self.assertRaises('InvalidVpc.Range',
                          client.create_vpc, rollback_fn=_rollback,
                          CidrBlock='10.0.0.0/15')

        # NOTE(andrey-mp): The smallest VPC you can create uses a /28 netmask
        self.assertRaises('InvalidVpc.Range',
                          client.create_vpc, rollback_fn=_rollback,
                          CidrBlock='10.0.0.0/29')

    @scenario.configure()
    @_runner(_run_both)
    def test_describe_non_existing_vpc_by_id(self,client):
        vpc_id = 'vpc-00000000'
        self.assertRaises('InvalidVpcID.NotFound',
                          client.describe_vpcs,
                          VpcIds=[vpc_id])

    @scenario.configure()
    @_runner(_run_both)
    def test_describe_non_existing_vpc_by_cidr(self,client):
        data = client.describe_vpcs(
            Filters=[{'Name': 'cidr', 'Values': ['123.0.0.0/16']}])
        self.assertEqual(0, len(data['Vpcs']))

    @scenario.configure()
    @_runner(_run_both)
    def test_describe_with_invalid_filter(self,client):
        cidr = '10.1.0.0/16'
        data = client.create_vpc(CidrBlock=cidr)
        vpc_id = data['Vpc']['VpcId']
        dv_clean = self.addResourceCleanUp(client.delete_vpc,
                                           VpcId=vpc_id)
        self.get_vpc_waiter(clientclient).wait_available(vpc_id)

        self.assertRaises('InvalidParameterValue',
                          client.describe_vpcs,
                          Filters=[{'Name': 'unknown', 'Values': ['unknown']}])

        data = client.delete_vpc(VpcId=vpc_id)
        self.cancelResourceCleanUp(dv_clean)
        self.get_vpc_waiter(client).wait_delete(vpc_id)

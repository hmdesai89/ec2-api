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




class SubnetTest(scenario.OpenStackScenario, base.EC2TestCase):

    BASE_CIDR = '10.2.0.0'
    VPC_CIDR = BASE_CIDR + '/20'
    vpc_id = None

    def __init__(self, *args, **kwargs):
        super(SubnetTest, self).__init__(*args, **kwargs)
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


    @classmethod
    @base.safe_setup
    def setUpClass(cls):
        super(SubnetTest, cls).setUpClass()
        if not base.TesterStateHolder().get_vpc_enabled():
            raise cls.skipException('VPC is disabled')

        data = cls.client.create_vpc(CidrBlock=cls.VPC_CIDR)
        cls.vpc_id = data['Vpc']['VpcId']
        cls.addResourceCleanUpStatic(cls.client.delete_vpc, VpcId=cls.vpc_id)
        cls.get_vpc_waiter(client).wait_available(cls.vpc_id)

    def test_create_delete_subnet(self):
        cidr = self.BASE_CIDR + '/24'
        data = self.client.create_subnet(VpcId=self.vpc_id,
                                         CidrBlock=cidr)
        subnet_id = data['Subnet']['SubnetId']
        res_clean = self.addResourceCleanUp(self.client.delete_subnet,
                                            SubnetId=subnet_id)
        self.assertEqual(cidr, data['Subnet']['CidrBlock'])
        self.assertIsNotNone(data['Subnet'].get('AvailableIpAddressCount'))

        self.get_subnet_waiter().wait_available(subnet_id)

        data = self.client.delete_subnet(SubnetId=subnet_id)
        self.cancelResourceCleanUp(res_clean)
        self.get_subnet_waiter().wait_delete(subnet_id)

        self.assertRaises('InvalidSubnetID.NotFound',
                          self.client.describe_subnets,
                          SubnetIds=[subnet_id])

        self.assertRaises('InvalidSubnetID.NotFound',
                          self.client.delete_subnet,
                          SubnetId=subnet_id)

    def test_dependency_subnet_to_vpc(self):
        data = self.client.create_vpc(CidrBlock=self.VPC_CIDR)
        vpc_id = data['Vpc']['VpcId']
        vpc_clean = self.addResourceCleanUp(self.client.delete_vpc,
                                            VpcId=vpc_id)
        self.get_vpc_waiter(client).wait_available(vpc_id)

        cidr = self.BASE_CIDR + '/24'
        data = self.client.create_subnet(VpcId=vpc_id, CidrBlock=cidr)
        subnet_id = data['Subnet']['SubnetId']
        res_clean = self.addResourceCleanUp(self.client.delete_subnet,
                                            SubnetId=subnet_id)
        self.get_subnet_waiter().wait_available(subnet_id)

        self.assertRaises('DependencyViolation',
                          self.client.delete_vpc,
                          VpcId=vpc_id)

        data = self.client.delete_subnet(SubnetId=subnet_id)
        self.cancelResourceCleanUp(res_clean)
        self.get_subnet_waiter().wait_delete(subnet_id)

        self.client.delete_vpc(VpcId=vpc_id)
        self.cancelResourceCleanUp(vpc_clean)

    #@testtools.skipUnless(
    #    CONF.aws.run_incompatible_tests,
    #    "bug with overlapped subnets")
    def test_create_overlapped_subnet(self):
        cidr = self.BASE_CIDR + '/24'
        data = self.client.create_subnet(VpcId=self.vpc_id, CidrBlock=cidr)
        subnet_id = data['Subnet']['SubnetId']
        res_clean = self.addResourceCleanUp(self.client.delete_subnet,
                                            SubnetId=subnet_id)
        self.get_subnet_waiter().wait_available(subnet_id)

        cidr = '10.2.0.128/26'

        def _rollback(fn_data):
            self.client.delete_subnet(SubnetId=data['Subnet']['SubnetId'])
        self.assertRaises('InvalidSubnet.Conflict',
                          self.client.create_subnet, rollback_fn=_rollback,
                          VpcId=self.vpc_id, CidrBlock=cidr)

        data = self.client.delete_subnet(SubnetId=subnet_id)
        self.cancelResourceCleanUp(res_clean)
        self.get_subnet_waiter().wait_delete(subnet_id)

    def test_create_subnet_invalid_cidr(self):
        def _rollback(fn_data):
            self.client.delete_subnet(SubnetId=fn_data['Subnet']['SubnetId'])

        # NOTE(andrey-mp): another cidr than VPC has
        cidr = '10.1.0.0/24'
        self.assertRaises('InvalidSubnet.Range',
                          self.client.create_subnet, rollback_fn=_rollback,
                          VpcId=self.vpc_id, CidrBlock=cidr)

        # NOTE(andrey-mp): bigger cidr than VPC has
        cidr = self.BASE_CIDR + '/19'
        self.assertRaises('InvalidSubnet.Range',
                          self.client.create_subnet, rollback_fn=_rollback,
                          VpcId=self.vpc_id, CidrBlock=cidr)

        # NOTE(andrey-mp): too small cidr
        cidr = self.BASE_CIDR + '/29'
        self.assertRaises('InvalidSubnet.Range',
                          self.client.create_subnet, rollback_fn=_rollback,
                          VpcId=self.vpc_id, CidrBlock=cidr)

    def test_describe_subnets_base(self):
        cidr = self.BASE_CIDR + '/24'
        data = self.client.create_subnet(VpcId=self.vpc_id, CidrBlock=cidr)
        subnet_id = data['Subnet']['SubnetId']
        res_clean = self.addResourceCleanUp(self.client.delete_subnet,
                                            SubnetId=subnet_id)
        self.get_subnet_waiter().wait_available(subnet_id)

        # NOTE(andrey-mp): by real id
        data = self.client.describe_subnets(SubnetIds=[subnet_id])
        self.assertEqual(1, len(data['Subnets']))

        # NOTE(andrey-mp): by fake id
        self.assertRaises('InvalidSubnetID.NotFound',
                          self.client.describe_subnets,
                          SubnetIds=['subnet-0'])

        data = self.client.delete_subnet(SubnetId=subnet_id)
        self.cancelResourceCleanUp(res_clean)
        self.get_subnet_waiter().wait_delete(subnet_id)

    def test_describe_subnets_filters(self):
        cidr = self.BASE_CIDR + '/24'
        data = self.client.create_subnet(VpcId=self.vpc_id, CidrBlock=cidr)
        subnet_id = data['Subnet']['SubnetId']
        res_clean = self.addResourceCleanUp(self.client.delete_subnet,
                                            SubnetId=subnet_id)
        self.get_subnet_waiter().wait_available(subnet_id)

        # NOTE(andrey-mp): by filter real cidr
        data = self.client.describe_subnets(
            Filters=[{'Name': 'cidr', 'Values': [cidr]}])
        self.assertEqual(1, len(data['Subnets']))

        # NOTE(andrey-mp): by filter fake cidr
        data = self.client.describe_subnets(
            Filters=[{'Name': 'cidr', 'Values': ['123.0.0.0/16']}])
        self.assertEqual(0, len(data['Subnets']))

        # NOTE(andrey-mp): by fake filter
        self.assertRaises('InvalidParameterValue',
                          self.client.describe_subnets,
                          Filters=[{'Name': 'fake', 'Values': ['fake']}])

        data = self.client.delete_subnet(SubnetId=subnet_id)
        self.cancelResourceCleanUp(res_clean)
        self.get_subnet_waiter().wait_delete(subnet_id)

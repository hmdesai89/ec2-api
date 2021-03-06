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

import uuid

from lxml import etree
import mock
from oslo_utils import timeutils
from oslotest import base as test_base

from ec2api.api import apirequest
from ec2api.tests.unit import fakes_request_response as fakes
from ec2api.tests.unit import matchers
from ec2api.tests.unit import tools


class EC2RequesterTestCase(test_base.BaseTestCase):

    def setUp(self):
        super(EC2RequesterTestCase, self).setUp()

        controller_patcher = mock.patch('ec2api.api.cloud.VpcCloudController')
        self.controller = controller_patcher.start().return_value
        self.addCleanup(controller_patcher.stop)

        self.fake_context = mock.NonCallableMock(request_id=str(uuid.uuid4()))

    def test_invoke_returns_data(self):
        self.controller.fake_action.return_value = fakes.DICT_FAKE_RESULT_DATA

        api_request = apirequest.APIRequest('FakeAction', 'fake_v1',
                                            {'Param': 'fake'})
        result = api_request.invoke(self.fake_context)

        self._compare_aws_xml('FakeActionResponse',
                              'http://vpc.ind-west-1.jiocloudservices.com/doc/fake_v1/',
                              self.fake_context.request_id,
                              fakes.DICT_FAKE_RESULT_DATA,
                              result)
        self.controller.fake_action.assert_called_once_with(
                self.fake_context, param='fake')

    def test_invoke_returns_true(self):
        self.controller.fake_action.return_value = True

        api_request = apirequest.APIRequest('FakeAction', 'fake_v1',
                                            {'Param': 'fake'})
        result = api_request.invoke(self.fake_context)

        self._compare_aws_xml('FakeActionResponse',
                              'http://vpc.ind-west-1.jiocloudservices.com/doc/fake_v1/',
                              self.fake_context.request_id,
                              {'return': True},
                              result)
        self.controller.fake_action.assert_called_once_with(
                self.fake_context, param='fake')

    def test_invoke_prepare_params(self):
        api_request = apirequest.APIRequest('FakeAction', 'fake_v1',
                                            fakes.DOTTED_FAKE_PARAMS)
        api_request.invoke(self.fake_context)

        self.controller.fake_action.assert_called_once_with(
                self.fake_context, **fakes.DICT_FAKE_PARAMS)

    def _compare_aws_xml(self, root_tag, xmlns, request_id, dict_data,
                         observed):
        # NOTE(ft): we cann't use matchers.XMLMatches since it makes comparison
        # based on the order of tags
        xml = etree.fromstring(observed)
        self.assertEqual(xmlns, xml.nsmap.get(None))
        observed_data = tools.parse_xml(observed)
        expected = {root_tag: tools.update_dict(dict_data,
                                                {'requestId': request_id})}
        self.assertThat(observed_data, matchers.DictMatches(expected))

    def test_render_response_ascii(self):
        req = apirequest.APIRequest("FakeAction", "FakeVersion", {})
        resp = {
            'string': 'foo',
            'int': 1,
        }
        data = req._render_response(resp, 'uuid')
        self.assertIn('<FakeActionResponse xmlns="http://vpc.ind-west-1.jiocloudservices.com/'
                      'doc/FakeVersion/', data)
        self.assertIn('<int>1</int>', data)
        self.assertIn('<string>foo</string>', data)

    def test_render_response_utf8(self):
        req = apirequest.APIRequest("FakeAction", "FakeVersion", {})
        resp = {
            'utf8': unichr(40960) + u'abcd' + unichr(1972)
        }
        data = req._render_response(resp, 'uuid')
        self.assertIn('<utf8>&#40960;abcd&#1972;</utf8>', data)

    # Tests for individual data element format functions

    def test_return_valid_isoformat(self):
        """Ensure that the ec2 api returns datetime in xs:dateTime

           (which apparently isn't datetime.isoformat())
           NOTE(ken-pepple): https://bugs.launchpad.net/nova/+bug/721297
        """
        conv = apirequest._database_to_isoformat
        # sqlite database representation with microseconds
        time_to_convert = timeutils.parse_strtime("2011-02-21 20:14:10.634276",
                                                  "%Y-%m-%d %H:%M:%S.%f")
        self.assertEqual(conv(time_to_convert), '2011-02-21T20:14:10.634Z')
        # mysqlite database representation
        time_to_convert = timeutils.parse_strtime("2011-02-21 19:56:18",
                                                  "%Y-%m-%d %H:%M:%S")
        self.assertEqual(conv(time_to_convert), '2011-02-21T19:56:18.000Z')

    def test_xmlns_version_matches_request_version(self):
        self.controller.fake_action.return_value = {}

        api_request = apirequest.APIRequest('FakeAction', '2010-10-30', {})
        result = api_request.invoke(self.fake_context)

        self._compare_aws_xml('FakeActionResponse',
                              'http://vpc.ind-west-1.jiocloudservices.com/doc/2010-10-30/',
                              self.fake_context.request_id,
                              {},
                              result)

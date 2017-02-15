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

"""
Starting point for routing EC2 requests.
"""
import hashlib
import json
import sys

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import timeutils
import requests
import six
import webob
import webob.dec
import webob.exc

from ec2api.api import apirequest
from ec2api.api import ec2utils
from ec2api.api import faults
from ec2api import context
from ec2api import exception
from ec2api.i18n import _
from ec2api import wsgi


LOG = logging.getLogger(__name__)

ec2_opts = [
    cfg.StrOpt('keystone_url',
               default='http://localhost',
               help='URL to get token from ec2 request.'),
    cfg.StrOpt('keystone_sig_url',
               default='$keystone_url/ec2-auth',
               help='URL to validate signature/access key in ec2 request.'),
    cfg.StrOpt('keystone_token_url',
               default='$keystone_url/token-auth',
               help='URL to validate token in ec2 request.'),
    cfg.IntOpt('ec2_timestamp_expiry',
               default=300,
               help='Time in seconds before ec2 timestamp expires'),
]

CONF = cfg.CONF
CONF.register_opts(ec2_opts)
CONF.import_opt('use_forwarded_for', 'ec2api.api.auth')


EMPTY_SHA256_HASH = (
    'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')
# This is the buffer size used when calculating sha256 checksums.
# Experimenting with various buffer sizes showed that this value generally
# gave the best result (in terms of performance).
PAYLOAD_BUFFER = 1024 * 1024


# Fault Wrapper around all EC2 requests #
class FaultWrapper(wsgi.Middleware):

    """Calls the middleware stack, captures any exceptions into faults."""

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        try:
            return req.get_response(self.application)
        except Exception:
            LOG.exception(_("FaultWrapper cathes error"))
            return faults.Fault(webob.exc.HTTPInternalServerError())


class RequestLogging(wsgi.Middleware):

    """Access-Log akin logging for all EC2 API requests."""

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        start = timeutils.utcnow()
        rv = req.get_response(self.application)
        self.log_request_completion(rv, req, start)
        return rv

    def log_request_completion(self, response, request, start):
        apireq = request.environ.get('ec2.request', None)
        if apireq:
            action = apireq.action
        else:
            action = None
        ctxt = request.environ.get('ec2api.context', None)
        delta = timeutils.utcnow() - start
        seconds = delta.seconds
        microseconds = delta.microseconds
        LOG.info(
            "%s.%ss %s %s %s %s %s [%s] %s %s",
            seconds,
            microseconds,
            request.remote_addr,
            request.method,
            "%s%s" % (request.script_name, request.path_info),
            action,
            response.status_int,
            request.user_agent,
            request.content_type,
            response.content_type,
            context=ctxt)


class InvalidCredentialsException(Exception):
    def __init__(self, msg):
        super(Exception, self).__init__()
        self.msg = msg


class EC2KeystoneAuth(wsgi.Middleware):

    """Authenticate an EC2 request with keystone and convert to context."""

    resourceIdMapping = {
                          'CreateVpc' : '*',
                          'CreateSubnet' : '*',
                          'CreateRouteTable' : '*',
                          'CreateRoute' : 'RouteTableId',
                          'CreateSecurityGroup' : '*',
                          'DeleteVpc' : 'VpcId',
                          'DeleteSubnet' : 'SubnetId',
                          'DeleteRouteTable' : 'RouteTableId',
                          'DeleteSecurityGroup' : 'GroupId',
                          'DeleteRoute' : 'RouteTableId',
                          'AssociateRouteTable' : 'SubnetId',
                          'DisassociateRouteTable' : 'AssociationId',
                          'AuthorizeSecurityGroupIngress' : 'GroupId',
                          'AuthorizeSecurityGroupEgress' : 'GroupId',
                          'RevokeSecurityGroupEgress' : 'GroupId',
                          'RevokeSecurityGroupIngress' : 'GroupId',
                          'DescribeVpcs' : '*',
                          'DescribeSubnets' : '*',
                          'DescribeRouteTables' : '*',
                          'DescribeSecurityGroups' : '*',
                          'AllocateAddress' : '',
                          'AssociateAddress' : '',
                          'DisassociateAddress' : '',
                          'ReleaseAddress' : '',
                          'DescribeAddresses' : '',
                        }

    armappingdict = {
                          'CreateVpc': {
                                          "action": "jrn:jcs:vpc:CreateVpc",
                                          "resource": "jrn:jcs:vpc::Vpc:",
                                          "implicit_allow": "False"
                                       },
                          'DeleteVpc':
                                       {
                                          "action": "jrn:jcs:vpc:DeleteVpc",
                                          "resource": "jrn:jcs:vpc::Vpc:",
                                          "implicit_allow": "False"
                                       },
                          'DescribeVpcs':
                                       {
                                          "action": "jrn:jcs:vpc:DescribeVpcs",
                                          "resource": "jrn:jcs:vpc::Vpc:",
                                          "implicit_allow": "False"
                                       },
                          'CreateSubnet':
                                       {
                                          "action": "jrn:jcs:vpc:CreateSubnet",
                                          "resource": "jrn:jcs:vpc::Subnet:",
                                          "implicit_allow": "False"
                                       },
                          'DeleteSubnet':
                                       {
                                          "action": "jrn:jcs:vpc:DeleteSubnet",
                                          "resource": "jrn:jcs:vpc::Subnet:",
                                          "implicit_allow": "False"
                                       },
                          'DescribeSubnets':
                                       {
                                          "action": "jrn:jcs:vpc:DescribeSubnets",
                                          "resource": "jrn:jcs:vpc::Subnet:",
                                          "implicit_allow": "False"
                                       },
                          'CreateRouteTable':
                                       {
                                          "action": "jrn:jcs:vpc:CreateRouteTable",
                                          "resource": "jrn:jcs:vpc::RouteTable:",
                                          "implicit_allow": "False"
                                       },
                          'DeleteRouteTable':
                                       {
                                          "action": "jrn:jcs:vpc:DeleteRouteTable",
                                          "resource": "jrn:jcs:vpc::RouteTable:",
                                          "implicit_allow": "False"
                                       },
                          'AssociateRouteTable':
                                       {
                                          "action": "jrn:jcs:vpc:AssociateRouteTable",
                                          "resource": "jrn:jcs:vpc::Subnet:",
                                          "implicit_allow": "False"
                                       },
                          'DisassociateRouteTable':
                                       {
                                          "action": "jrn:jcs:vpc:DisassociateRouteTable",
                                          "resource": "jrn:jcs:vpc::AssociatedRouteTable:",
                                          "implicit_allow": "False"
                                       },
                          'DescribeRouteTables':
                                       {
                                          "action": "jrn:jcs:vpc:DescribeRouteTables",
                                          "resource": "jrn:jcs:vpc::RouteTable:",
                                          "implicit_allow": "False"
                                       },
                          'CreateRoute':
                                       {
                                          "action": "jrn:jcs:vpc:CreateRoute",
                                          "resource": "jrn:jcs:vpc::RouteTable:",
                                          "implicit_allow": "False"
                                       },
                          'DeleteRoute':
                                       {
                                          "action": "jrn:jcs:vpc:DeleteRoute",
                                          "resource": "jrn:jcs:vpc::RouteTable:",
                                          "implicit_allow": "False"
                                       },
                          'AllocateAddress': None,
                          'AssociateAddress': None,
                          'DisassociateAddress': None,
                          'ReleaseAddress': None,
                          'DescribeAddresses': None,
                          'CreateSecurityGroup':
                                       {
                                          "action": "jrn:jcs:vpc:CreateSecurityGroup",
                                          "resource": "jrn:jcs:vpc::SecurityGroup:",
                                          "implicit_allow": "False"
                                       },
                          'DeleteSecurityGroup':
                                       {
                                          "action": "jrn:jcs:vpc:DeleteSecurityGroup",
                                          "resource": "jrn:jcs:vpc::SecurityGroup:",
                                          "implicit_allow": "False"
                                       },
                          'DescribeSecurityGroups':
                                       {
                                          "action": "jrn:jcs:vpc:DescribeSecurityGroups",
                                          "resource": "jrn:jcs:vpc::SecurityGroup:",
                                          "implicit_allow": "False"
                                       },
                          'AuthorizeSecurityGroupEgress':
                                       {
                                          "action": "jrn:jcs:vpc:AuthorizeSecurityGroupEgress",
                                          "resource": "jrn:jcs:vpc::SecurityGroup:",
                                          "implicit_allow": "False"
                                       },
                          'AuthorizeSecurityGroupIngress':
                                       {
                                          "action": "jrn:jcs:vpc:AuthorizeSecurityGroupIngress",
                                          "resource": "jrn:jcs:vpc::SecurityGroup:",
                                          "implicit_allow": "False"
                                       },
                          'RevokeSecurityGroupEgress':
                                       {
                                          "action": "jrn:jcs:vpc:RevokeSecurityGroupEgress",
                                          "resource": "jrn:jcs:vpc::SecurityGroup:",
                                          "implicit_allow": "False"
                                       },
                          'RevokeSecurityGroupIngress':
                                       {
                                          "action": "jrn:jcs:vpc:RevokeSecurityGroupIngress",
                                          "resource": "jrn:jcs:vpc::SecurityGroup:",
                                          "implicit_allow": "False"
                                       },
                    }

    def _get_signature(self, req):
        """Extract the signature from the request.

        This can be a get/post variable or for version 4 also in a header
        called 'Authorization'.
        - params['Signature'] == version 0,1,2,3
        - params['X-Amz-Signature'] == version 4
        - header 'Authorization' == version 4
        """
        sig = req.params.get('Signature') or req.params.get('X-Amz-Signature')
        if sig is not None:
            return sig

        if 'Authorization' not in req.headers:
            return None

        auth_str = req.headers['Authorization']
        if not auth_str.startswith('AWS4-HMAC-SHA256'):
            return None

        return auth_str.partition("Signature=")[2].split(',')[0]

    def _get_access(self, req):
        """Extract the access key identifier.

        For version 0/1/2/3 this is passed as the AccessKeyId parameter, for
        version 4 it is either an X-Amz-Credential parameter or a Credential=
        field in the 'Authorization' header string.
        """
        access = req.params.get('JCSAccessKeyId')
        if access is not None:
            return access

        cred_param = req.params.get('X-Amz-Credential')
        if cred_param:
            access = cred_param.split("/")[0]
            if access is not None:
                return access

        if 'Authorization' not in req.headers:
            return None
        auth_str = req.headers['Authorization']
        if not auth_str.startswith('AWS4-HMAC-SHA256'):
            return None
        cred_str = auth_str.partition("Credential=")[2].split(',')[0]
        return cred_str.split("/")[0]

    def _get_auth_token(self, req):
        """Extract the Auth token from the request

        This is the header X-Auth-Token present in the request
        """
        auth_token = None

        auth_token = req.headers.get('X-Auth-Token')

        return auth_token

    def _get_x_forwarded_for(self, req):
        client_ip = req.headers.get('X-Forwarded-For')
        return client_ip

    def _get_resource_id(self, req, action):

        resource = None     
        resourceId = None
        
        resource = self.resourceIdMapping[action]

        if '*' == resource:
            resourceId = resource
        elif '' == resource:
            resourceId = resource
        else:
            resourceId = req.params.get(resource)

        return resourceId

    def _get_action_resource_mapping(self, req):

        armvalue = None

        action = req.params.get('Action')

        try:
            actiondict = self.armappingdict[action]
            if actiondict == None:
                # No mapping available. Pass an empty list.
                armvalue = []
            else:
                # Create a new instance of the action resource mapping dictionary for subsequent 
                # modifications and pass it as a member of a list
                armvalue = [dict(actiondict)]
        except KeyError:
            return armvalue

        return armvalue
             
    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        request_id = context.generate_request_id()

        # NOTE(alevine) We need to calculate the hash here because
        # subsequent access to request modifies the req.body so the hash
        # calculation will yield invalid results.

        headers = {'Content-Type': 'application/json'}

        auth_token = self._get_auth_token(req)

        if None == auth_token:
            signature = self._get_signature(req)
            if not signature:
                msg = _("Signature not provided")
                return faults.ec2_error_response(request_id, "AuthFailure", msg,
                                                 status=400)
            access = self._get_access(req)
            if not access:
                msg = _("Access key not provided")
                return faults.ec2_error_response(request_id, "AuthFailure", msg,
                                                 status=400)

            if 'X-Amz-Signature' in req.params or 'Authorization' in req.headers:
                params = {}
            else:
                # Make a copy of args for authentication and signature verification
                params = dict(req.params)
                # Not part of authentication args
                params.pop('Signature', None)

        #version = params.pop('Version')

        action = req.params.get('Action')

        arm = {}
        arm = self._get_action_resource_mapping(req)

        if None == arm:
            msg = _("Action : " + action + " Not Found")
            return faults.ec2_error_response(request_id, "ActionNotFound", msg,
                                             status=404)

        resourceId = None
        resourceId = self._get_resource_id(req, action)

        if None == resourceId:
            msg = _("Action is : " + action + " and ResourceId Not Found")
            return faults.ec2_error_response(request_id, "ResourceIdNotFound", msg,
                                             status=404)
        if '' != resourceId:
            arm[0]['resource'] = arm[0].get('resource') + resourceId

        if auth_token:
            data = {}

            iam_validation_url = CONF.keystone_token_url

            headers['X-Auth-Token'] = auth_token
            data['action_resource_list'] = arm

            data = jsonutils.dumps(data)
        else:
            host = req.host.split(':')[0]

            cred_dict = {
                          'access': access,
                          'action_resource_list': arm,
                          'body_hash': '',
                          'headers': {},
                          'host': host,
                          'signature': signature,
                          'verb': req.method,
                          'path': '/',
                          'params': params,
                       }

            iam_validation_url = CONF.keystone_sig_url

            if "ec2" in iam_validation_url:
                creds = {'ec2Credentials': cred_dict}
            else:
                creds = {'auth': {'OS-KSEC2:ec2Credentials': cred_dict}}

            data = jsonutils.dumps(creds)

        client_ip = self._get_x_forwarded_for(req)
        LOG.info(_('Client IP of request:{request_id} is {client_ip}'.\
                    format(request_id=request_id, client_ip=client_ip)))
        if client_ip:
            headers['X-Forwarded-For'] = client_ip
        verify = CONF.ssl_ca_file or not CONF.ssl_insecure
        response = requests.request('POST', iam_validation_url, verify=verify,
                                    data=data, headers=headers)
        status_code = response.status_code
        if status_code != 200:
            LOG.error("Request headers - %s", str(headers))
            LOG.error("Request params - %s", str(data))
            LOG.error("Response headers - %s", str(response.headers))
            LOG.error("Response content - %s", str(response._content))
            msg = response.reason
            return faults.ec2_error_response(request_id, "AuthFailure", msg,
                                             status=status_code)
        result = response.json()

        try:
            user_id = result['user_id']
            project_id = result['account_id']

            if auth_token:
                token_id = auth_token
            else:
                token_id = result['token_id']

            if not token_id or not project_id or not user_id:
                raise KeyError

            user_name = project_name = 'default'

            roles = []
            catalog = []
        except (AttributeError, KeyError):
            LOG.exception(_("Keystone failure"))
            msg = _("Failure communicating with keystone")
            return faults.ec2_error_response(request_id, "AuthFailure", msg,
                                             status=400)

        remote_address = req.remote_addr
        if CONF.use_forwarded_for:
            remote_address = req.headers.get('X-Forwarded-For',
                                             remote_address)

        ctxt = context.RequestContext(user_id, project_id,
                                      user_name=user_name,
                                      project_name=project_name,
                                      roles=roles,
                                      auth_token=token_id,
                                      remote_address=remote_address,
                                      service_catalog=catalog,
                                      api_version=req.params.get('Version'),
                                      request_id=request_id)

        req.environ['ec2api.context'] = ctxt

        return self.application

class EC2KeystoneAuthInternal(wsgi.Middleware):

    """Authenticate an EC2 request with keystone and convert to context."""

    allowedaction = {
                          'CreateExtnetwork' : '',
                          'UpdateQuota' : '',
                          'ShowQuota' : '',
                          'DescribeFlowLog' : '',
                          'CreatePassAccount' : '',
                          'DeletePassAccount' : ''
                        }



    def _get_auth_token(self, req):
        """Extract the Auth token from the request

        This is the header X-Auth-Token present in the request
        """
        auth_token = None

        auth_token = req.headers.get('X-Auth-Token')

        return auth_token

    def _get_x_forwarded_for(self, req):
        client_ip = req.headers.get('X-Forwarded-For')
        return client_ip


    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        request_id = context.generate_request_id()

        # NOTE(alevine) We need to calculate the hash here because
        # subsequent access to request modifies the req.body so the hash
        # calculation will yield invalid results.

        headers = {'Content-Type': 'application/json'}

        auth_token = self._get_auth_token(req)

        if None == auth_token:
                msg = _("AuthToken in needed for internal api call")
                return faults.ec2_error_response(request_id, "AuthFailure", msg,
                                                 status=400)

        action = req.params.get('Action')

        if None == action:
            msg = _("Action : " + action + " Not Found")
            return faults.ec2_error_response(request_id, "ActionNotFound", msg,
                                             status=404)
        elif action not in self.allowedaction :
                msg = _("Action not allowed in internal api call")
                return faults.ec2_error_response(request_id, "AuthFailure", msg,
                                                 status=400)
        if auth_token:
            data = {}

            iam_validation_url = CONF.keystone_token_url

            headers['X-Auth-Token'] = auth_token

            data = jsonutils.dumps(data)

        client_ip = self._get_x_forwarded_for(req)
        LOG.info(_('Client IP of request:{request_id} is {client_ip}'.\
                    format(request_id=request_id, client_ip=client_ip)))
        if client_ip:
            headers['X-Forwarded-For'] = client_ip
        verify = CONF.ssl_ca_file or not CONF.ssl_insecure
        response = requests.request('POST', iam_validation_url, verify=verify,
                                    data=data, headers=headers)
        status_code = response.status_code
        if status_code != 200:
            LOG.error("Request headers - %s", str(headers))
            LOG.error("Request params - %s", str(data))
            LOG.error("Response headers - %s", str(response.headers))
            LOG.error("Response content - %s", str(response._content))
            msg = response.reason
            return faults.ec2_error_response(request_id, "AuthFailure", msg,
                                             status=status_code)
        result = response.json()

        try:
            user_id = result['user_id']
            project_id = result['account_id']

            if auth_token:
                token_id = auth_token
            else:
                token_id = result['token_id']

            if not token_id or not project_id or not user_id:
                raise KeyError

            user_name = project_name = 'default'
            roles = []
            catalog = []
        except (AttributeError, KeyError):
            LOG.exception(_("Keystone failure"))
            msg = _("Failure communicating with keystone")
            return faults.ec2_error_response(request_id, "AuthFailure", msg,
                                             status=400)

        remote_address = req.remote_addr
        if CONF.use_forwarded_for:
            remote_address = req.headers.get('X-Forwarded-For',
                                             remote_address)

        ctxt = context.RequestContext(user_id, project_id,
                                      user_name=user_name,
                                      project_name=project_name,
                                      roles=roles,
                                      auth_token=token_id,
                                      remote_address=remote_address,
                                      service_catalog=catalog,
                                      api_version=req.params.get('Version'),
                                      request_id=request_id)

        req.environ['ec2api.context'] = ctxt

        return self.application




class Requestify(wsgi.Middleware):

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        non_args = ['Action', 'Signature', 'JCSAccessKeyId', 'SignatureMethod',
                    'SignatureVersion', 'Version', 'Timestamp']
        args = dict(req.params)
        try:
            expired = ec2utils.is_ec2_timestamp_expired(
                req.params,
                expires=CONF.ec2_timestamp_expiry)
            if expired:
                msg = _("Timestamp failed validation.")
                LOG.exception(msg)
                raise webob.exc.HTTPForbidden(explanation=msg)

            # Raise KeyError if omitted
            action = req.params['Action']
            # Fix bug lp:720157 for older (version 1) clients
            version = req.params.get('SignatureVersion')
            if version and int(version) == 1:
                non_args.remove('SignatureMethod')
                if 'SignatureMethod' in args:
                    args.pop('SignatureMethod')
            for non_arg in non_args:
                args.pop(non_arg, None)
        except KeyError:
            raise webob.exc.HTTPBadRequest()
        except exception.InvalidRequest as err:
            raise webob.exc.HTTPBadRequest(explanation=unicode(err))

        LOG.debug('action: %s', action)
        for key, value in args.items():
            LOG.debug('arg: %(key)s\t\tval: %(value)s',
                      {'key': key, 'value': value})

        # Success!
        api_request = apirequest.APIRequest(
            action, req.params['Version'], args)
        req.environ['ec2.request'] = api_request
        return self.application


def exception_to_ec2code(ex):
    """Helper to extract EC2 error code from exception.

    For other than EC2 exceptions (those without ec2_code attribute),
    use exception name.
    """
    if hasattr(ex, 'ec2_code'):
        code = ex.ec2_code
    else:
        code = type(ex).__name__
    return code


def ec2_error_ex(ex, req, unexpected=False):
    """Return an EC2 error response.

    Return an EC2 error response based on passed exception and log
    the exception on an appropriate log level:

        * DEBUG: expected errors
        * ERROR: unexpected errors

    All expected errors are treated as client errors and 4xx HTTP
    status codes are always returned for them.

    Unexpected 5xx errors may contain sensitive information,
    suppress their messages for security.
    """
    code = exception_to_ec2code(ex)
    for status_name in ('code', 'status', 'status_code', 'http_status'):
        status = getattr(ex, status_name, None)
        if isinstance(status, int):
            break
    else:
        status = 500

    if unexpected:
        log_fun = LOG.error
        log_msg = _("Unexpected %(ex_name)s raised: %(ex_str)s")
        exc_info = sys.exc_info()
    else:
        log_fun = LOG.debug
        log_msg = _("%(ex_name)s raised: %(ex_str)s")
        exc_info = None

    context = req.environ['ec2api.context']
    request_id = context.request_id
    log_msg_args = {
        'ex_name': type(ex).__name__,
        'ex_str': unicode(ex)
    }
    log_fun(log_msg % log_msg_args, context=context, exc_info=exc_info)

    if unexpected and status >= 500:
        message = _('Unknown error occurred.')
    elif getattr(ex, 'message', None):
        message = unicode(ex.message)
    elif ex.args and any(arg for arg in ex.args):
        message = " ".join(map(unicode, ex.args))
    else:
        message = unicode(ex)
    if unexpected:
        # Log filtered environment for unexpected errors.
        env = req.environ.copy()
        for k in env.keys():
            if not isinstance(env[k], six.string_types):
                env.pop(k)
        log_fun(_('Environment: %s') % jsonutils.dumps(env))
    return faults.ec2_error_response(request_id, code, message, status=status)


class Executor(wsgi.Application):

    """Execute an EC2 API request.

    Executes 'ec2.action', passing 'ec2api.context' and
    'ec2.action_args' (all variables in WSGI environ.)  Returns an XML
    response, or a 400 upon failure.
    """

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        context = req.environ['ec2api.context']
        api_request = req.environ['ec2.request']
        try:
            result = api_request.invoke(context)
        except Exception as ex:
            return ec2_error_ex(
                ex, req, unexpected=not isinstance(ex, exception.EC2Exception))
        else:
            resp = webob.Response()
            resp.status = 200
            resp.headers['Content-Type'] = 'text/xml'
            resp.body = str(result)

            return resp

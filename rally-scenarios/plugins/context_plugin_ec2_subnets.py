from rally.common.i18n import _
from rally.common import log as logging
from rally.common import utils as rutils
from rally import consts
from rally import osclients
from rally.plugins.openstack.wrappers import network as network_wrapper
from rally.task import context


LOG = logging.getLogger(__name__)


@context.configure(name="prepare_ec2_subnet", order=110)
class PrepareEC2SubnetContext(context.Context):


    CONFIG_SCHEMA= {
        "type" : "object",
        "$schema": consts.JSON_SCHEMA,
        "additionalProperties": True,
        "properties": {
            "vpc_id": {
                "type" : "string",
            },
        }
    def __init__(self, ctx):
        super(PrepareEC2SubnetContext, self).__init__(ctx)
        self.net_wrapper = network_wrapper.wrap(
            osclients.Clients(self.context["admin"]["credential"]),
            self, config=self.config)
        self.net_wrapper.start_cidr = '10.0.0.0/16'

    @logging.log_task_wrapper(LOG.info, _("Enter context: `EC2 creds`"))
    def setup(self):
        """This method is called before the task start."""
        try:
            for user in self.context['users']:
                osclient = osclients.Clients(user['credential'])
                keystone = osclient.keystone()
                creds = keystone.ec2.list(user['id'])
                if not creds:
                    creds = keystone.ec2.create(user['id'], user['tenant_id'])
                else:
                    creds = creds[0]
                url = 'http://192.168.100.49:8788/services/Cloud'
                url_parts = url.rpartition(':')
                nova_url = (url_parts[0] + ':8773/'
                            + url_parts[2].partition('/')[2])
               client = botocoreclient.get_ec2_client(
                    url, 'RegionOne', creds.access, creds.secret)
               vpc_id = client.create_vpc()

                user['ec2args'] = {
                    'region': 'RegionOne',
                    'url': url,
                    'nova_url': nova_url,
                    'access': creds.access,
                    'secret': creds.secret
                    'vpc_id': 
                }
                

                    
        except Exception as e:
            msg = "Can't prepare ec2 client: %s" % e.message
            if logging.is_debug():
                LOG.exception(msg)
            else:
                LOG.warning(msg)

    @logging.log_task_wrapper(LOG.info, _("Exit context: `EC2 creds`"))
    def cleanup(self):
        try:
            #if self.net_wrapper.SERVICE_IMPL == consts.Service.NEUTRON:
            #        network = self.context["tenants"][tenant_id]["network"]
            #       self.net_wrapper.delete_network(network)
            print 'clenaup'
        except Exception as e:
            msg = "Can't cleanup ec2 client: %s" % e.message
            if logging.is_debug():
                LOG.exception(msg)
            else:
                LOG.warning(msg)



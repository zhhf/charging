# Copyright 2011 VMware, Inc
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

import eventlet
import inspect
import logging as std_logging
import os
import random

from oslo.config import cfg

from charging.common import config
#from charging.common import legacy
#from charging import context
from charging import manager
from charging import charging_plugin_base_v2
#from charging.openstack.common.db.sqlalchemy import session
from charging.openstack.common import excutils
#from charging.openstack.common import importutils
from charging.openstack.common import log as logging
#from charging.openstack.common import loopingcall
#from charging.openstack.common.rpc import service
#from charging.openstack.common.service import ProcessLauncher
from charging import wsgi

#def _(msg):
#    return msg

service_opts = [
    cfg.IntOpt('periodic_interval',
               default=40,
               help=_('Seconds between running periodic tasks')),
    cfg.IntOpt('api_workers',
               default=0,
               help=_('Number of separate worker processes for service')),
    cfg.IntOpt('rpc_workers',
               default=0,
               help=_('Number of RPC worker processes for service')),
    cfg.IntOpt('periodic_fuzzy_delay',
               default=5,
               help=_('Range of seconds to randomly delay when starting the '
                      'periodic task scheduler to reduce stampeding. '
                      '(Disable by setting to 0)')),
]
CONF = cfg.CONF
CONF.register_opts(service_opts)


CLI_OPTIONS = [
    cfg.StrOpt('os-username',
               deprecated_group="DEFAULT",
               default=os.environ.get('OS_USERNAME', 'ceilometer'),
               help='Username to use for openstack service access'),
    cfg.StrOpt('os-password',
               deprecated_group="DEFAULT",
               secret=True,
               default=os.environ.get('OS_PASSWORD', 'admin'),
               help='Password to use for openstack service access'),
    cfg.StrOpt('os-tenant-id',
               deprecated_group="DEFAULT",
               default=os.environ.get('OS_TENANT_ID', ''),
               help='Tenant ID to use for openstack service access'),
    cfg.StrOpt('os-tenant-name',
               deprecated_group="DEFAULT",
               default=os.environ.get('OS_TENANT_NAME', 'admin'),
               help='Tenant name to use for openstack service access'),
    cfg.StrOpt('os-cacert',
               default=os.environ.get('OS_CACERT', None),
               help='Certificate chain for SSL validation'),
    cfg.StrOpt('os-auth-url',
               deprecated_group="DEFAULT",
               default=os.environ.get('OS_AUTH_URL',
                                      'http://localhost:5000/v2.0'),
               help='Auth URL to use for openstack service access'),
    cfg.StrOpt('os-region-name',
               deprecated_group="DEFAULT",
               default=os.environ.get('OS_REGION_NAME', None),
               help='Region name to use for openstack service endpoints'),
    cfg.StrOpt('os-endpoint-type',
               default=os.environ.get('OS_ENDPOINT_TYPE', 'publicURL'),
               help='Type of endpoint in Identity service catalog to use for '
                    'communication with OpenStack services.'),
]
cfg.CONF.register_cli_opts(CLI_OPTIONS, group="service_credentials")

LOG = logging.getLogger(__name__)


class WsgiService(object):
    """Base class for WSGI based services.

    For each api you define, you must also define these flags:
    :<api>_listen: The address on which to listen
    :<api>_listen_port: The port on which to listen

    """

    def __init__(self, app_name):
        self.app_name = app_name
        self.wsgi_app = None

    def start(self):
        self.wsgi_app = _run_wsgi(self.app_name)

    def wait(self):
        self.wsgi_app.wait()


class ChargingApiService(WsgiService):
    """Class for Charging-api service."""

    @classmethod
    def create(cls, app_name='charging'):

        # Setup logging early, supplying both the CLI options and the
        # configuration mapping from the config file
        # We only update the conf dict for the verbose and debug
        # flags. Everything else must be set up in the conf file...
        # Log the options used when starting if we're in debug mode...

        config.setup_logging(cfg.CONF)
        #legacy.modernize_quantum_config(cfg.CONF)
        # Dump the initial option values
        cfg.CONF.log_opt_values(LOG, std_logging.DEBUG)
        service = cls(app_name)
        return service


def serve_wsgi(cls):

    try:
        try:
            service = cls.create()
            service.start()
        except RuntimeError:
            LOG.exception(_('Error occurred: trying old api-paste.ini.'))
            #service = cls.create('quantum')
            #service.start()
    except Exception:
        with excutils.save_and_reraise_exception():
            LOG.exception(_('Unrecoverable error: please check log '
                            'for details.'))

    return service


class RpcWorker(object):
    """Wraps a worker to be handled by ProcessLauncher"""
    def __init__(self, plugin):
        self._plugin = plugin
        self._server = None

    def start(self):
        # We may have just forked from parent process.  A quick disposal of the
        # existing sql connections avoids producing errors later when they are
        # discovered to be broken.
        session.get_engine(sqlite_fk=True).pool.dispose()
        self._server = self._plugin.start_rpc_listener()

    def wait(self):
        if isinstance(self._server, eventlet.greenthread.GreenThread):
            self._server.wait()

    def stop(self):
        if isinstance(self._server, eventlet.greenthread.GreenThread):
            self._server.kill()
            self._server = None


def serve_rpc():
    plugin = manager.ChargingManager.get_plugin()
    #LOG.debug('zhf.plugin=%s' % plugin)   

    # If 0 < rpc_workers then start_rpc_listener would be called in a
    # subprocess and we cannot simply catch the NotImplementedError.  It is
    # simpler to check this up front by testing whether the plugin overrides
    # start_rpc_listener.
    base = charging_plugin_base_v2.ChargingPluginBaseV2
    if plugin.__class__.start_rpc_listener == base.start_rpc_listener:
        LOG.debug(_("Active plugin doesn't implement start_rpc_listener"))
        if 0 < cfg.CONF.rpc_workers:
            msg = _("'rpc_workers = %d' ignored because start_rpc_listener "
                    "is not implemented.")
            LOG.error(msg, cfg.CONF.rpc_workers)
        raise NotImplementedError

    try:
        rpc = RpcWorker(plugin)

        if cfg.CONF.rpc_workers < 1:
            rpc.start()
            return rpc
        else:
            launcher = ProcessLauncher(wait_interval=1.0)
            launcher.launch_service(rpc, workers=cfg.CONF.rpc_workers)
            return launcher
    except Exception:
        with excutils.save_and_reraise_exception():
            LOG.exception(_('Unrecoverable error: please check log '
                            'for details.'))


def _run_wsgi(app_name):
    app = config.load_paste_app(app_name)
    #LOG.debug('zhf.app=%s' % app)
    #LOG.debug('zhf.app.__class__=%s' % app.__class__)
    if not app:
        LOG.error(_('No known API applications configured.'))
        return
    server = wsgi.Server("Charging")
    server.start(app, cfg.CONF.bind_port, cfg.CONF.bind_host,
                 workers=cfg.CONF.api_workers)
    # Dump all option values here after all options are parsed
    cfg.CONF.log_opt_values(LOG, std_logging.DEBUG)
    LOG.info(_("Charging service started, listening on %(host)s:%(port)s"),
             {'host': cfg.CONF.bind_host,
              'port': cfg.CONF.bind_port})
    return server


#class Service(service.Service):
#    """Service object for binaries running on hosts.
#
#    A service takes a manager and enables rpc by listening to queues based
#    on topic. It also periodically runs tasks on the manager.
#    """
#
#    def __init__(self, host, binary, topic, manager, report_interval=None,
#                 periodic_interval=None, periodic_fuzzy_delay=None,
#                 *args, **kwargs):
#
#        self.binary = binary
#        self.manager_class_name = manager
#        manager_class = importutils.import_class(self.manager_class_name)
#        self.manager = manager_class(host=host, *args, **kwargs)
#        self.report_interval = report_interval
#        self.periodic_interval = periodic_interval
#        self.periodic_fuzzy_delay = periodic_fuzzy_delay
#        self.saved_args, self.saved_kwargs = args, kwargs
#        self.timers = []
#        super(Service, self).__init__(host, topic, manager=self.manager)
#
#    def start(self):
#        self.manager.init_host()
#        super(Service, self).start()
#        if self.report_interval:
#            pulse = loopingcall.FixedIntervalLoopingCall(self.report_state)
#            pulse.start(interval=self.report_interval,
#                        initial_delay=self.report_interval)
#            self.timers.append(pulse)
#
#        if self.periodic_interval:
#            if self.periodic_fuzzy_delay:
#                initial_delay = random.randint(0, self.periodic_fuzzy_delay)
#            else:
#                initial_delay = None
#
#            periodic = loopingcall.FixedIntervalLoopingCall(
#                self.periodic_tasks)
#            periodic.start(interval=self.periodic_interval,
#                           initial_delay=initial_delay)
#            self.timers.append(periodic)
#        self.manager.after_start()
#
#    def __getattr__(self, key):
#        manager = self.__dict__.get('manager', None)
#        return getattr(manager, key)
#
#    @classmethod
#    def create(cls, host=None, binary=None, topic=None, manager=None,
#               report_interval=None, periodic_interval=None,
#               periodic_fuzzy_delay=None):
#        """Instantiates class and passes back application object.
#
#        :param host: defaults to CONF.host
#        :param binary: defaults to basename of executable
#        :param topic: defaults to bin_name - 'nova-' part
#        :param manager: defaults to CONF.<topic>_manager
#        :param report_interval: defaults to CONF.report_interval
#        :param periodic_interval: defaults to CONF.periodic_interval
#        :param periodic_fuzzy_delay: defaults to CONF.periodic_fuzzy_delay
#
#        """
#        if not host:
#            host = CONF.host
#        if not binary:
#            binary = os.path.basename(inspect.stack()[-1][1])
#        if not topic:
#            topic = binary.rpartition('neutron-')[2]
#            topic = topic.replace("-", "_")
#        if not manager:
#            manager = CONF.get('%s_manager' % topic, None)
#        if report_interval is None:
#            report_interval = CONF.report_interval
#        if periodic_interval is None:
#            periodic_interval = CONF.periodic_interval
#        if periodic_fuzzy_delay is None:
#            periodic_fuzzy_delay = CONF.periodic_fuzzy_delay
#        service_obj = cls(host, binary, topic, manager,
#                          report_interval=report_interval,
#                          periodic_interval=periodic_interval,
#                          periodic_fuzzy_delay=periodic_fuzzy_delay)
#
#        return service_obj
#
#    def kill(self):
#        """Destroy the service object."""
#        self.stop()
#
#    def stop(self):
#        super(Service, self).stop()
#        for x in self.timers:
#            try:
#                x.stop()
#            except Exception:
#                LOG.exception(_("Exception occurs when timer stops"))
#                pass
#        self.timers = []
#
#    def wait(self):
#        super(Service, self).wait()
#        for x in self.timers:
#            try:
#                x.wait()
#            except Exception:
#                LOG.exception(_("Exception occurs when waiting for timer"))
#                pass
#
#    def periodic_tasks(self, raise_on_error=False):
#        """Tasks to be run at a periodic interval."""
#        ctxt = context.get_admin_context()
#        self.manager.periodic_tasks(ctxt, raise_on_error=raise_on_error)
#
#    def report_state(self):
#        """Update the state of this service."""
#        # Todo(gongysh) report state to neutron server
#        pass

#!/usr/bin/env python

# Copyright 2011 VMware, Inc.
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

# If ../neutron/__init__.py exists, add ../ to Python search path, so that
# it will override what happens to be installed in /usr/(local/)lib/python...

import eventlet
import sys

from oslo.config import cfg

from charging.common import config
from charging import service

#from charging.openstack.common import gettextutils
from charging.openstack.common import log as logging
#gettextutils.install('charging', lazy=True)

LOG = logging.getLogger(__name__)


def main():
    eventlet.monkey_patch()

    # the configuration will be read into the cfg.CONF global data structure
    config.parse(sys.argv[1:])
    if not cfg.CONF.config_file:
        sys.exit(_("ERROR: Unable to find configuration file via the default"
                   " search paths (~/.charging/, ~/, /etc/charging/, /etc/) and"
                   " the '--config-file' option!"))
    try:
        pool = eventlet.GreenPool()

        charging_api = service.serve_wsgi(service.ChargingApiService)
        api_thread = pool.spawn(charging_api.wait)

        try:
            charging_rpc = service.serve_rpc()
        except NotImplementedError:
            LOG.info(_("RPC was already started in parent process by plugin."))
        else:
            rpc_thread = pool.spawn(charging_rpc.wait)

            # api and rpc should die together.  When one dies, kill the other.
            rpc_thread.link(lambda gt: api_thread.kill())
            api_thread.link(lambda gt: rpc_thread.kill())

        #LOG.debug('zhf.lock_path=%s' % cfg.CONF.lock_path)
        #LOG.debug('zhf.os_username=%s' % cfg.CONF.service_credentials.os_username)
        #LOG.debug('zhf.before wait')
        pool.waitall()
    except KeyboardInterrupt:
        pass
    except RuntimeError as e:
        sys.exit(_("ERROR: %s") % e)


if __name__ == "__main__":
    main()

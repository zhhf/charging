# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright 2012 OpenStack Foundation
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

from oslo.config import cfg
import webob.dec
import webob.exc

from charging import context
from charging.openstack.common import log as logging
from charging.openstack.common.middleware import request_id
from charging import wsgi

LOG = logging.getLogger(__name__)


class ChargingKeystoneContext(wsgi.Middleware):
    """Make a request context from keystone headers."""

    @webob.dec.wsgify
    def __call__(self, req):
        # Determine the user ID
        user_id = req.headers.get('X_USER_ID')
        if not user_id:
            LOG.debug(_("X_USER_ID is not found in request"))
            return webob.exc.HTTPUnauthorized()

        # Determine the tenant
        tenant_id = req.headers.get('X_PROJECT_ID')

        # Suck out the roles
        roles = [r.strip() for r in req.headers.get('X_ROLES', '').split(',')]

        # Human-friendly names
        tenant_name = req.headers.get('X_PROJECT_NAME')
        user_name = req.headers.get('X_USER_NAME')

        # Use request_id if already set
        req_id = req.environ.get(request_id.ENV_REQUEST_ID)

        # Create a context with the authentication data
        #LOG.debug('zhf.user_id=%s,tenant=%s,roles=%s,user_name=%s,tenant_name=%s,request_id=%s' % (user_id, tenant_id, 
        #              roles, user_name, tenant_name, req_id))
        ctx = context.Context(user_id, tenant_id, roles=roles,
                              user_name=user_name, tenant_name=tenant_name,
                              request_id=req_id,
                              is_admin=True,load_admin_roles=False)

        # Inject the context...
        req.environ['charging.context'] = ctx

        return self.application


def pipeline_factory(loader, global_conf, **local_conf):
    """Create a paste pipeline based on the 'auth_strategy' config option."""
    #LOG.debug('zhf.loader=%s' % loader)
    pipeline = local_conf[cfg.CONF.auth_strategy]
    pipeline = pipeline.split()
    #LOG.debug('zhf.pipeline=%s' % pipeline)
    filters = [loader.get_filter(n) for n in pipeline[:-1]]
    #LOG.debug('zhf.filters=%s' % filters)
    app = loader.get_app(pipeline[-1])
    filters.reverse()
    for filter in filters:
        app = filter(app)
    return app

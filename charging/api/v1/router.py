# Copyright (c) 2012 OpenStack Foundation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from oslo.config import cfg
import routes as routes_mapper
import six.moves.urllib.parse as urlparse
import webob
import webob.dec
import webob.exc

#from neutron.api import extensions
from charging.api.v1 import attributes
from charging.api.v1 import base
#from neutron import manager
from charging.openstack.common import log as logging
from charging import wsgi

LOG = logging.getLogger(__name__)

#RESOURCES = {'network': 'networks',
#             'subnet': 'subnets',
#             'port': 'ports'}
RESOURCES = ['flavor', 'tenant']
SUB_RESOURCES = {}
COLLECTION_ACTIONS = ['index', 'create']
#MEMBER_ACTIONS = ['show', 'update', 'delete']
MEMBER_ACTIONS = [('create', 'POST'),
                  ('show', 'GET'),
                  ('delete', 'DELETE'),
                  ('update', 'PUT'), ]
#REQUIREMENTS = {'id': attributes.UUID_PATTERN, 'format': 'xml|json'}
REQUIREMENTS = {'resource': 'flavor|tenant'}


class Index(wsgi.Application):
    def __init__(self, resources):
        self.resources = resources

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        metadata = {'application/xml': {'attributes': {
                    'resource': ['name', 'collection'],
                    'link': ['href', 'rel']}}}

        layout = []
        for name, collection in self.resources.iteritems():
            href = urlparse.urljoin(req.path_url, collection)
            resource = {'name': name,
                        'collection': collection,
                        'links': [{'rel': 'self',
                                   'href': href}]}
            layout.append(resource)
        response = dict(resources=layout)
        content_type = req.best_match_content_type()
        body = wsgi.Serializer(metadata=metadata).serialize(response,
                                                            content_type)
        return webob.Response(body=body, content_type=content_type)


class AddTenantTotal(wsgi.Application):
    xml_deserializer = wsgi.XMLDeserializer(attributes.get_attr_metadata())
    default_deserializers = {'application/xml': xml_deserializer,
                             'application/json': wsgi.JSONDeserializer()}
    xml_serializer = wsgi.XMLDictSerializer(attributes.get_attr_metadata())
    default_serializers = {'application/xml': xml_serializer,
                           'application/json': wsgi.JSONDictSerializer()}
    format_types = {'xml': 'application/xml',
                    'json': 'application/json'}
    action_status = dict(create=201, delete=204)

    #default_deserializers.update(deserializers or {})
    #default_serializers.update(serializers or {})

    deserializers = default_deserializers
    serializers = default_serializers

    def __init__(self, resources):
        self.resources = resources

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        metadata = {'application/xml': {'attributes': {
                    'resource': ['name', 'collection'],
                    'link': ['href', 'rel']}}}
        layout = []
        #response = dict(resources=layout)
        response = None
        content_type = req.best_match_content_type()
        body = wsgi.Serializer(metadata=metadata).serialize(response,
                                                            content_type)
        route_args = req.environ.get('wsgiorg.routing_args')
        if route_args:
            args = route_args[1].copy()
        else:
            args = {}
        args.pop('controller', None)
        #fmt = args.pop('format', None)
        action = args.pop('action', None)

        #LOG.debug('zhf.content=%s' % content_type)
        deserializer = self.deserializers.get(content_type)
        serializer = self.serializers.get(content_type)
        if req.body:
                args['body'] = deserializer.deserialize(req.body)['body']
        #LOG.debug('zhf.args=%s' % args)

        
        return webob.Response(body=body, content_type=content_type)

    def create(self, request, id, **kwargs):
        tenant_id = kwargs.get('tenant_id', None)
        money = kwargs.get('body',{}).get('money', -1)
        #LOG.debug('zhf.req=%s' % request.__class__)
        context = request.context
        #LOG.debug('zhf.context=%s' % context)
        with context.session.begin(subtransactions=True):
            # The 'shared' attribute for subnets is for internal plugin
            # use only. It is not exposed through the API
            args = {'tenant_id': tenant_id,
                    'id': uuidutils.generate_uuid(),
                    'name': 'test_name',
                    'domain_id': 'test_domain',
                    'money': money}
            money_T = models_v2.Money_Tenant(**args)
            context.session.add(money_T)

class APIRouter(wsgi.Router):

    @classmethod
    def factory(cls, global_config, **local_config):
        return cls(**local_config)

    def __init__(self, **local_config):
        mapper = routes_mapper.Mapper()
        #plugin = manager.NeutronManager.get_plugin()
        plugin = None
        #ext_mgr = extensions.PluginAwareExtensionManager.get_instance()
        #ext_mgr.extend_resources("2.0", attributes.RESOURCE_ATTRIBUTE_MAP)

        #col_kwargs = dict(collection_actions=COLLECTION_ACTIONS,
        #                  member_actions=MEMBER_ACTIONS)

        #def _map_resource(collection, resource, params, parent=None):
        #    LOG.debug('zhf.collection=%s,resource=%s,params=%s,parent=%s' % (collection, resource, params, parent))
        #    allow_bulk = cfg.CONF.allow_bulk
        #    allow_pagination = cfg.CONF.allow_pagination
        #    allow_sorting = cfg.CONF.allow_sorting
        #    controller = base.create_resource(
        #        collection, resource, plugin, params, allow_bulk=allow_bulk,
        #        parent=parent, allow_pagination=allow_pagination,
        #        allow_sorting=allow_sorting)
        #    path_prefix = None
        #    if parent:
        #        path_prefix = "/%s/{%s_id}/%s" % (parent['collection_name'],
        #                                          parent['member_name'],
        #                                          collection)
        #    mapper_kwargs = dict(controller=controller,
        #                         requirements=REQUIREMENTS,
        #                         path_prefix=path_prefix,
        #                         **col_kwargs)
        #    return mapper.collection(collection, resource,
        #                             **mapper_kwargs)

        #mapper.connect('index', '/zhf', controller=Index(RESOURCES))
        #controller = base.create_tenant_resource()
        #mapper.connect('getTenantTotal', '/{tenant_id}', action='show', 
        #        controller=controller, conditions=dict(method=["GET",]))
        #mapper.connect('addTenantTotal', '/{tenant_id}', action='create', 
        #        controller=controller, conditions=dict(method=["POST",]))
        #mapper.connect('delTenantTotal', '/{tenant_id}', action='delete', 
        #        controller=controller, conditions=dict(method=["DELETE",]))
        #mapper.connect('updateTenantTotal', '/{tenant_id}', action='update', 
        #        controller=controller, conditions=dict(method=["PUT",]))
        #LOG.debug('zhf.mapper=%s' % mapper)

        controller = base.create_resource_new()
        for resource in RESOURCES:
            mapper.connect('','/{resource}/list',
                           action = 'list',
                           controller = controller,
                           conditions = dict(method=['GET',]))
            for (action,method) in MEMBER_ACTIONS:
                mapper.connect('%s_%s' % (resource,action), 
                               '/{resource}/{id}', 
                               requirements=REQUIREMENTS,
                               action = action, 
                               controller = controller, 
                               conditions=dict(method=[method,]))


        #for resource in RESOURCES:
        #    _map_resource(RESOURCES[resource], resource,
        #                  attributes.RESOURCE_ATTRIBUTE_MAP.get(
        #                      RESOURCES[resource], dict()))

        #for resource in SUB_RESOURCES:
        #    _map_resource(SUB_RESOURCES[resource]['collection_name'], resource,
        #                  attributes.RESOURCE_ATTRIBUTE_MAP.get(
        #                      SUB_RESOURCES[resource]['collection_name'],
        #                      dict()),
        #                  SUB_RESOURCES[resource]['parent'])

        super(APIRouter, self).__init__(mapper)

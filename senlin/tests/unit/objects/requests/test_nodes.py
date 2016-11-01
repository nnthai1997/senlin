# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
import copy

from oslo_config import cfg

from senlin.objects.requests import nodes
from senlin.tests.unit.common import base as test_base

CONF = cfg.CONF
CONF.import_opt('default_action_timeout', 'senlin.common.config')


class TestNodeCreate(test_base.SenlinTestCase):

    body = {
        'name': 'test-node',
        'profile_id': 'test-profile',
    }

    def test_node_create_request_body(self):
        sot = nodes.NodeCreateRequestBody(**self.body)
        self.assertEqual('test-node', sot.name)
        self.assertEqual('test-profile', sot.profile_id)

        sot.obj_set_defaults()

        self.assertEqual('', sot.cluster_id)
        self.assertEqual('', sot.role)
        self.assertEqual({}, sot.metadata)

    def test_node_create_request_body_full(self):
        body = copy.deepcopy(self.body)
        body['role'] = 'master'
        body['cluster_id'] = 'cluster-01'
        body['metadata'] = {'foo': 'bar'}
        sot = nodes.NodeCreateRequestBody(**body)
        self.assertEqual('test-node', sot.name)
        self.assertEqual('test-profile', sot.profile_id)
        self.assertEqual('cluster-01', sot.cluster_id)
        self.assertEqual('master', sot.role)
        self.assertEqual({'foo': 'bar'}, sot.metadata)

    def test_request_body_to_primitive(self):
        sot = nodes.NodeCreateRequestBody(**self.body)
        res = sot.obj_to_primitive()
        self.assertEqual(
            {
                'name': u'test-node',
                'profile_id': u'test-profile'
            },
            res['senlin_object.data']
        )
        self.assertEqual('NodeCreateRequestBody',
                         res['senlin_object.name'])
        self.assertEqual('senlin', res['senlin_object.namespace'])
        self.assertEqual('1.0', res['senlin_object.version'])
        self.assertIn('profile_id', res['senlin_object.changes'])
        self.assertIn('name', res['senlin_object.changes'])

    def test_request_to_primitive(self):
        body = nodes.NodeCreateRequestBody(**self.body)
        request = {'node': body}
        sot = nodes.NodeCreateRequest(**request)
        self.assertIsInstance(sot.node, nodes.NodeCreateRequestBody)

        self.assertEqual('test-node', sot.node.name)
        self.assertEqual('test-profile', sot.node.profile_id)

        res = sot.obj_to_primitive()
        self.assertEqual(['node'], res['senlin_object.changes'])
        self.assertEqual('NodeCreateRequest', res['senlin_object.name'])
        self.assertEqual('senlin', res['senlin_object.namespace'])
        self.assertEqual('1.0', res['senlin_object.version'])
        data = res['senlin_object.data']['node']
        self.assertIn('profile_id', data['senlin_object.changes'])
        self.assertIn('name', data['senlin_object.changes'])
        self.assertEqual('NodeCreateRequestBody',
                         data['senlin_object.name'])
        self.assertEqual('senlin', data['senlin_object.namespace'])
        self.assertEqual('1.0', data['senlin_object.version'])
        self.assertEqual(
            {'name': u'test-node', 'profile_id': u'test-profile'},
            data['senlin_object.data']
        )


class TestNodeList(test_base.SenlinTestCase):

    def test_node_list_request_body_full(self):
        params = {
            'cluster_id': '8c3c9af7-d768-4c5a-a21e-5261b22d749d',
            'name': ['node01'],
            'status': ['ACTIVE'],
            'limit': 3,
            'marker': 'f1ed0d50-7651-4599-a8cb-c86e9c7123f5',
            'sort': 'name:asc',
            'project_safe': False,
        }
        sot = nodes.NodeListRequest(**params)
        self.assertEqual('8c3c9af7-d768-4c5a-a21e-5261b22d749d',
                         sot.cluster_id)
        self.assertEqual(['node01'], sot.name)
        self.assertEqual(['ACTIVE'], sot.status)
        self.assertEqual(3, sot.limit)
        self.assertEqual('f1ed0d50-7651-4599-a8cb-c86e9c7123f5', sot.marker)
        self.assertEqual('name:asc', sot.sort)
        self.assertFalse(sot.project_safe)

    def test_node_list_request_body_default(self):
        sot = nodes.NodeListRequest()
        sot.obj_set_defaults()
        self.assertTrue(sot.project_safe)


class TestNodeGet(test_base.SenlinTestCase):

    def test_node_get_request_full(self):
        params = {
            'identity': 'node-001',
            'show_details': True,
        }
        sot = nodes.NodeGetRequest(**params)
        self.assertEqual('node-001', sot.identity)
        self.assertTrue(sot.show_details)

    def test_node_get_request_default(self):
        sot = nodes.NodeGetRequest()
        sot.obj_set_defaults()
        self.assertFalse(sot.show_details)
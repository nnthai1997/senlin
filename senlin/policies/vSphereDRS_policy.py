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

"""
Policy for placing nodes based on Nova server groups.

NOTE: How placement policy works
Input:
  cluster: cluster whose nodes are to be manipulated.
  action.data['placement']:
    - count: number of nodes to create; it can be decision from a scaling
             policy. If no scaling policy is in effect, the count will be
             assumed to be 1.
Output:
  stored in action.data: A dictionary containing scheduling decisions made.
  {
    'status': 'OK',
    'placement': {
      'count': 2,
      'placements': [
        {
          'host_name': 'openstack_drs',
          'scheduler_hints': {
                'group': group_id,
                },
        },
        {
          'host_name': 'openstack_drs',
          'scheduler_hints': {
                'group': group_id,
                },
        },
      ]
    }
  }
"""

import re
import six

from oslo_context import context as oslo_context
from oslo_log import log as logging
from senlin.common import constraints
from senlin.common import consts
from senlin.common import exception
from senlin.common.i18n import _
from senlin.common.i18n import _LE
from senlin.common import schema
from senlin.drivers import base as driver_base
from senlin.engine import cluster as cluster_mod
from senlin.engine import cluster_policy
from senlin.policies import base as policy_base
from senlin.profiles import base as profile_base


LOG = logging.getLogger(__name__)


class vSphereDRSPolicy(policy_base.Policy):
    """Policy for placing members of a cluster based on server groups.

    This policy is expected to be enforced before new member(s) added to an
    existing cluster.
    """

    VERSION = '1.0'

    PRIORITY = 300

    # TODO(Xinhui Li): support resize
    TARGET = [
        ('BEFORE', consts.CLUSTER_SCALE_OUT),
    ]

    PROFILE_TYPE = [
        'os.nova.server',
    ]

    KEYS = (
        SERVER_GROUP
    ) = (
        'server_group'
    )

    _GROUP_KEYS = (
        GROUP_NAME, GROUP_POLICIES,
    ) = (
        'name', 'policies',
    )

    _GROUP_POLICIES = (
        AFFINITY, ANTI_AFFINITY,
    ) = (
        'affinity', 'anti-affinity',
    )

    properties_schema = {
        SERVER_GROUP: schema.Map(
            _('Properties of the VM server group'),
            schema={
                GROUP_NAME: schema.String(
                    _('The name of the server group'),
                ),
                GROUP_POLICIES: schema.String(
                    _('The server group policies.'),
                    default=AFFINITY,
                    constraints=[
                        constraints.AllowedValues(_GROUP_POLICIES),
                    ],
                ),
            },
        ),
    }

    def __init__(self, name, spec, **kwargs):
        super(vSphereDRSPolicy, self).__init__(name, spec, **kwargs)
        self._novaclient = None

    def nova(self, obj):
        """Construct nova client based on object.

        :param obj: Object for which the client is created. It is expected to
                    be None when retrieving an existing client. When creating
                    a client, it conatins the user and project to be used.
        """
        if self._novaclient is not None:
            return self._novaclient
        params = self._build_conn_params(obj)
        self._novaclient = driver_base.SenlinDriver().compute(params)
        return self._novaclient

    def attach(self, cluster):
        """Routine to be invoked when policy is to be attached to a cluster.

        :para cluster: The Target cluster to be attached to;
        :returns: When the operation was successful, returns a tuple (True,
                  message); otherwise, return a tuple (False, error).
        """
        data = {}
        nc = self.nova(cluster)

        group = self.properties.get(self.SERVER_GROUP)
        group_name = group.get(self.GROUP_NAME, None)

        if group_name is None:
            profile = profile_base.Profile.load(
                oslo_context.get_current(), profile_id=cluster.profile_id)
            if 'scheduler_hints' in profile.spec:
                hints = profile.spec['scheduler_hints']
                group_name = hints.get('group', None)

        if group_name is not None:
            try:
                server_group = nc.get_server_group(group_name)
            except exception.InternalError as ex:
                msg = _('Failed in retrieving server group')
                LOG.exception(_LE('%(msg)s: %(ex)s') % {
                    'msg': msg, 'ex': six.text_type(ex)})
                return False, msg
            data['group_id'] = server_group.id
            data['inherited_group'] = True

        if data.get('group_id') is None:
            policies = group.get(self.GROUP_POLICIES, self.ANTI_AFFINITY)

            try:
                server_group = nc.create_server_group(policies)
            except exception.InternalError as ex:
                msg = _('Failed in creating server group')
                LOG.exception(_LE('%(msg)s: %(ex)s') % {
                    'msg': msg, 'ex': six.text_type(ex)})
                return False, msg
            data['group_id'] = server_group.id
            data['inherited_group'] = False

        policy_data = self._build_policy_data(data)

        return True, policy_data

    def detach(self, cluster):
        """Routine to be called when the policy is detached from a cluster.

        :param cluster: The cluster from which the policy is to be detached.
        :returns: When the operation was successful, returns a tuple of
                  (True, data) where the data contains references to the
                  resources created; otherwise returns a tuple of (False,
                  error) where the err contains a error message.
        """

        reason = _('Server group resources deletion succeeded')

        cp = cluster_policy.ClusterPolicy.load(oslo_context.get_current(),
                                               cluster.id, self.id)
        if cp is None or cp.data is None:
            return True, reason

        policy_data = self._extract_policy_data(cp.data)
        if policy_data is None:
            return True, reason

        group_id = policy_data.get('group_id', None)
        inherited_group = policy_data.get('inherited_group', False)

        if group_id and not inherited_group:
            try:
                self.nova(cluster).delete_server_group(group_id)
            except exception.InternalError as ex:
                msg = _('Failed in deleting server group')
                LOG.exception(_LE('%(msg)s: %(ex)s') % {
                    'msg': msg, 'ex': six.text_type(ex)})
                return False, msg

        return True, reason

    def pre_op(self, cluster_id, action):
        """Routine to be called before an 'CLUSTER_SCALE_OUT' action.

        For this particular policy, we take this chance to intelligently
        select the most proper hypervisor/vsphere cluster to create nodes.
        In order to realize the function, we need to create construct meta
        to handle affinity/anti-affinity then update the profile with the
        specific parameters at first

        :param cluster_id: ID of the cluster on which the relevant action
                            is to be executed.
        :param action: The action object that triggered this operation.
        :returns: Nothing.
        """

        if not action.context.is_admin:
            action.data['status'] = policy_base.CHECK_ERROR
            action.data['status_reason'] = _('Policy only applicable to '
                                             'admin-owned clusters.')
            return

        pd = action.data.get('creation', None)

        if pd is not None:
            self.count = pd.get('count', 1)
            # 'nova' is default_availability_zone of Nova settings
            zone_name = pd.get('zone', 'nova')
        else:
            self.count = action.inputs.get('count', 1)
            zone_name = 'nova'

        cluster = cluster_mod.Cluster.load(action.context, cluster_id)
        nc = self.nova(cluster)

        hypervisors = nc.get_hypervisors()
        hv_id = ''
        pattern = re.compile(r'.*drs*', re.I)
        for hypervisor in hypervisors:
            match = pattern.match(hypervisor.hypervisor_hostname)
            if match:
                hv_id = hypervisor.id
                break

        if hv_id:
            hv_info = nc.get_hypervisor_by_id(hv_id)
            hostname = hv_info['service']['host']
            zone_host_name = ":".join([zone_name, hostname])

        cp = cluster_policy.ClusterPolicy.load(action.context, cluster_id,
                                               self.id)
        policy_data = self._extract_policy_data(cp.data)
        group_id = policy_data['group_id']

        pd = {
            'count': self.count,
            'placements': [
                {
                    'zone': zone_host_name,
                    'scheduler_hints': {
                        'group': group_id,
                    },
                },
            ] * self.count,
        }
        action.data.update({'placement': pd})
        action.store(action.context)

        return

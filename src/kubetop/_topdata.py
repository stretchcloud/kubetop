# Copyright Least Authority Enterprises.
# See LICENSE for details.

"""
Retrieve resource usage data by Kubernetes Objects.

Theory of Operation
===================

#. Combine Kubernetes API server location with a resource collection object.
#. Collect resource usage information via the Heapster service on the
   Kubernetes API server.
"""

from __future__ import unicode_literals

from twisted.internet.defer import gatherResults

import attr
import attr.validators

from treq import json_content
from treq.client import HTTPClient

from txkube import IKubernetes, network_kubernetes_from_context


def make_source(reactor, config_path, context_name):
    """
    Get a source of Kubernetes resource usage data.
    """
    kubernetes = network_kubernetes_from_context(
        reactor, context_name, config_path
    )
    return _Source(kubernetes=kubernetes)


@attr.s(frozen=True)
class _Source(object):
    kubernetes = attr.ib(validator=attr.validators.provides(IKubernetes))

    def pods(self):
        base_url = self.kubernetes.base_url
        d = self._client()

        def _pods(client):
            return gatherResults([
                self._pod_usage_from_client(client, base_url),
                self.kubernetes.versioned_client().addCallback(self._pod_info),
            ]).addCallback(
                lambda usage_info: {
                    "usage": usage_info[0],
                    "info": usage_info[1],
                },
            )
        d.addCallback(_pods)
        return d

    def nodes(self):
        base_url = self.kubernetes.base_url
        d = self._client()

        def _nodes(client):
            return gatherResults([
                self._node_usage_from_client(client, base_url),
                self._node_info_from_client(client, base_url),
            ]).addCallback(
                lambda usage_info: {
                    "usage": usage_info[0],
                    "info": usage_info[1],
                },
            )
        d.addCallback(_nodes)
        return d

    def _client(self):
        d = self.kubernetes.versioned_client()
        d.addCallback(lambda client: HTTPClient(agent=client.agent))
        return d

    def _pod_usage_from_client(self, client, base_url):
        d = self.kubernetes.versioned_client()
        d.addCallback(lambda client: client.list(client.model.v1.Namespace))

        def got_namespaces(namespaces):
            d = gatherResults(
                client.get(
                    base_url.asText() + self.pod_location(ns.metadata.name)
                ).addCallback(
                    json_content
                )
                for ns
                in namespaces.items
            )

            def combine(pod_usages):
                result = []
                for usage in pod_usages:
                    if usage["items"] is None:
                        continue
                    for item in usage["items"]:
                        result.append(item)
                return {"items": result}
            d.addCallback(combine)
            return d
        d.addCallback(got_namespaces)
        return d

    def _pod_info(self, client):
        return client.list(client.model.v1.Pod)

    def pod_location(self, namespace):
        # kubectl --v=11 top pods
        return (
            "/api/v1/namespaces/kube-system/services/http:heapster:"
            "/proxy/apis/metrics/v1alpha1/namespaces/{namespace}/pods?"
            "labelSelector="
        ).format(namespace=namespace)

    def _node_usage_from_client(self, client, base_url):
        d = client.get(base_url.asText() + self.node_location())
        d.addCallback(json_content)
        return d

    def node_location(self):
        # url-hacked from pod_location... I found no docs that clearly explain
        # what is going on here.
        # https://github.com/kubernetes/heapster/blob/master/docs/model.md
        # provides some hints but it's documenting the actual Heapster API
        # which requires port-forwarding into the Heapster pod to access.
        return (
            "/api/v1/namespaces/kube-system/services/http:heapster:"
            "/proxy/apis/metrics/v1alpha1/nodes"
        )

    def _node_info_from_client(self, client, base_url):
        d = client.get(base_url.asText() + "/api/v1/nodes")
        d.addCallback(json_content)
        return d

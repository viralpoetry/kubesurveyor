#!/usr/bin/env python3

__author__ = "Peter Gasper"
__version__ = "1.0.1"
__license__ = "MIT"

import os
import sys
import yaml
import argparse
from graphviz import Digraph
from kubernetes import client, config

ns = {
    "namespace": "",
    "version": __version__,  # program version
    "ingress": {},  # fqdn to service mapping
    "service": {},  # service to deployment - 1 to 1 mapping
    "pod": {},  # pod to container - 1 to N mapping
}


def get_pods(client, namespace):
    # name, ports
    v1 = client.CoreV1Api()
    ret = v1.list_namespaced_pod(namespace=namespace)
    for pod in ret.items:
        pod_name = ""
        containers = []
        for container in pod.spec.containers:
            # collect container name and ports used
            ports = []
            try:
                for port in container.ports:
                    port = port.to_dict()
                    # store name, and the actual port in case name is not used
                    if "name" in port:
                        if port["name"] is not None:
                            ports.append(port["name"])
                    if "container_port" in port:
                        ports.append(port["container_port"])
            except TypeError:
                # container does not have ports
                pass
            containers.append([container.name, ports])
        if "job-name" in pod.metadata.labels:
            # skip cron-jobs
            continue
        # beware, if elif order matters !
        if "app" in pod.metadata.labels:
            pod_name = pod.metadata.labels["app"]
        elif "statefulset.kubernetes.io/pod-name" in pod.metadata.labels:
            pod_name = pod.metadata.labels["statefulset.kubernetes.io/pod-name"]
        elif "app.kubernetes.io/name" in pod.metadata.labels:
            pod_name = pod.metadata.labels["app.kubernetes.io/name"]
        else:
            continue
        # safe to a global variable
        if pod_name not in ns["pod"]:
            ns["pod"][pod_name] = {}
        for container in containers:
            # { "<pod>": {"<container>": ["web", "8080", "<other port>"]}}
            ns["pod"][pod_name][container[0]] = container[1]


def get_services(client, namespace):
    v1 = client.CoreV1Api()
    ret = v1.list_namespaced_service(namespace=namespace)
    for service in ret.items:
        selector = {}
        ports = []
        if service.spec.selector:
            selector = service.spec.selector  # .to_dict()
        else:
            # what if there are no selectors?
            # Could be a service for some external deployment
            continue
        for port in service.spec.ports:
            port = port.to_dict()
            if "target_port" in port:
                ports.append(port["target_port"])
        # safe to a global variable
        if service.metadata.name not in ns["service"]:
            ns["service"][service.metadata.name] = {}
        ns["service"][service.metadata.name]["ports"] = ports
        ns["service"][service.metadata.name]["selector"] = selector


def get_ingresses(client, namespace):
    v1betaExt = client.ExtensionsV1beta1Api()
    ret = v1betaExt.list_namespaced_ingress(namespace=namespace)
    for ingress in ret.items:
        ns["ingress"][ingress.metadata.name] = {}
        for rule in ingress.spec.rules:  # list
            rule = rule.to_dict()
            ns["ingress"][ingress.metadata.name][rule["host"]] = {}
            for k in rule.keys():
                # get associated rules
                if k == "host":
                    # no rule here
                    continue
                else:
                    ns["ingress"][ingress.metadata.name][rule["host"]][k] = rule[k]


def visualize():
    dot_root = Digraph(
        name="Kubernetes Namespace visualisation",
        comment="namespace view",
        strict="true",
    )
    # graph attributes
    dot_root.graph_attr["label"] = ns["namespace"] + " namespace"
    # dot_root.graph_attr["pad"] = "1"
    dot_root.graph_attr["rankdir"] = "LR"
    dot_root.graph_attr["ranksep"] = "5.2 equally"
    dot_root.graph_attr["fontsize"] = "12"
    dot_root.graph_attr["fontname"] = "Sans-Serif"
    dot_root.graph_attr["nodesep"] = "0.3"
    # dot_root.graph_attr["splines"] = "spline"
    dot_root.graph_attr["concentrate"] = "true"
    # node attributes
    dot_root.node_attr["shape"] = "box"
    # colors modified from the command line
    dot_root.graph_attr["bgcolor"] = "black"  # background
    dot_root.graph_attr["fontcolor"] = "white"  # text
    dot_root.graph_attr["color"] = "white"  # for drawings
    dot_root.node_attr["fontcolor"] = "white"  # text
    dot_root.node_attr["color"] = "white"  # for drawings
    dot_root.node_attr["pencolor"] = "white"  # cluster bounding box
    dot_root.edge_attr["fontcolor"] = "white"  # text
    dot_root.edge_attr["color"] = "white"  # for drawings
    dot_root.edge_attr["pencolor"] = "white"  # cluster bounding box
    # fillcolor, labelfontcolor - defaults to fontcolor
    dot_root.edge_attr["headport"] = "w"
    dot_root.edge_attr["tailport"] = "e"

    # ingress, service & pod subgraphs
    common_node_attrs = {"shape": "box"}
    dot_ingress = Digraph(name="ingress", node_attr={"arrowType": "empty"})
    dot_service = Digraph(name="clusterservice")
    dot_service.attr(label="Services", pad="1")
    dot_pods = Digraph(name="clusterpods")
    dot_pods.attr(label="Pods", pad="1")

    # lets track existing items
    existing_pods = {}
    # Create "ingress to service" nodes and edges
    for i in ns["ingress"].keys():
        for host in ns["ingress"][i].keys():
            # show just the hostname in dot graph
            dot_ingress.node(host)
            for proto in ns["ingress"][i][host].keys():
                # get associated rules
                for rule in ns["ingress"][i][host][proto]:
                    for path in ns["ingress"][i][host][proto][rule]:
                        service_name = path["backend"]["service_name"]
                        # put service to dot
                        dot_service.node(service_name)
                        # edge between the ingress and the service
                        # let's use hostname instead of ingress label
                        dot_root.edge(host, service_name, label=proto)
    # make sure each name is unique in dot
    index = 0
    # Create "service to container" nodes and edges
    for pod, containers in ns["pod"].items():
        # we wants to have unique names
        index = index + 1
        # if pod does not exist in dot, create it once
        if pod not in existing_pods:
            # we don't have this pod yet
            dot_pod = Digraph(
                name="cluster" + pod + str(index),
                graph_attr={"label": pod},
            )
            existing_pods[pod] = str(index)
        # get only container names, not the ports
        container_names = list(containers.keys())
        # does any service refer this pod or its containers ?
        for (
            container_name,
            container_ports,
        ) in containers.items():
            for service_name in ns["service"].keys():
                # we are using strict=true so duplicates does not concern us that much
                dot_service.node(service_name)
                # get pod and ports service is connecting to
                pod_selector = list(ns["service"][service_name]["selector"].values())
                ports = ns["service"][service_name]["ports"]
                # check for common element
                if (pod in pod_selector) or (set(pod_selector) & set(container_names)):
                    dot_pod.node(
                        container_name + existing_pods[pod],
                        container_name,
                    )
                    # FIXME, we are checking just the first service port
                    if ports[0] in container_ports:
                        # lets create an edge between the service and a container
                        # do not forget to use unique pod index for the edge
                        dot_root.edge(
                            service_name,
                            container_name + existing_pods[pod],
                        )
                dot_pods.subgraph(dot_pod)
    # push the subgraphs to the dot_root
    dot_root.subgraph(dot_ingress)
    dot_root.subgraph(dot_service)
    dot_root.subgraph(dot_pods)
    return dot_root


def ns_to_yaml():
    """Dump namespace dictionary in YAML format."""
    print(yaml.dump(ns, default_flow_style=False), file=sys.stdout)


def yaml_to_ns(input_file):
    """Load YAML from file to a global variable."""
    global ns
    ns = yaml.load(input_file, Loader=yaml.BaseLoader)


def get_all(client, namespace):
    # TODO check if namespace is available with the current context
    get_services(client, namespace)
    get_pods(client, namespace)
    get_ingresses(client, namespace)


def main(args):
    # https://github.com/kubernetes-client/python/issues/1131#issuecomment-749452174
    if args.context:
        try:
            config.load_kube_config(context=args.context)
        except config.config_exception.ConfigException:
            print(
                "Error: Context %s not found in the kube-config file." % args.context,
                file=sys.stdout,
            )
            return
    else:
        # load everything from .kube/config
        config.load_kube_config()
    cc = client.Configuration.get_default_copy()
    # do not validate SSL certificate
    if args.insecure:
        cc.verify_ssl = False
        # disable "Adding certificate verification is strongly advised" warnings
        import urllib3

        urllib3.disable_warnings()
    # FIXME use proper CA if available
    # cc.ssl_ca_cert = os.environ.get("REQUESTS_CA_BUNDLE")
    client.Configuration.set_default(cc)
    namespace = args.namespace
    ns["namespace"] = namespace
    input_file = None
    # decide if we are loading from an actual cluster or existing yaml file
    if not args.load:
        # we are not loading from a yaml file
        get_all(client, namespace)
    else:
        # load yaml file loaded via stdin to a `ns` global var
        input_file = sys.stdin
        yaml_to_ns(input_file)
    # decide if we are visualising or storing internal state to a file
    if args.save:
        # show crawled yaml instead of visualization
        ns_to_yaml()
    else:
        viz_dot = visualize()
        if args.out == "dot":
            # return only dot file
            print(viz_dot, file=sys.stdout)
        if args.out == "png":
            # this one will return png and dot file
            viz_dot.format = "png"
            # dot_root.view()
            viz_dot.render(filename=namespace)


def parse_args():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Kubesurveyor: Good enough Kubernetes namespace visualization tool.

        Examples:
            # Show '<namespace>' namespace as a 'dot' language graph, using currently active K8S config context
            kubesurveyor <namespace>

            # ignore K8S API certificate errors
            kubesurveyor <namespace> --insecure

            # Specify context to be used
            kubesurveyor <namespace> --context <context>

            # Dump crawled namespace data to a YAML format for later processing
            kubesurveyor <namespace> --context <context> --save > namespace.yaml

            # Load from YAML file, show as 'dot' language graph
            cat namespace.yaml | kubesurveyor <namespace> --load

            # Load from `YAML` file and render as `png` visualization to a current working directory
            cat namespace.yaml | kubesurveyor <namespace> --load --out png
            """,
    )

    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s (version {version})".format(version=__version__),
    )

    # Required positional argument
    parser.add_argument(
        "namespace",
        default="default",
        help="The Kubernetes namespace (default 'default').",
    )
    parser.add_argument(
        "-c",
        "--context",
        action="store",
        dest="context",
        help="Kubernetes config file context.",
    )
    parser.add_argument(
        "-o",
        "--out",
        action="store",
        dest="out",
        default="dot",
        help="Visualisation format. ['dot', 'png'] (default 'dot').",
    )

    # arguments related to an internals
    parser.add_argument(
        "-s",
        "--save",
        action="store_true",
        default=False,
        help="Save crawled namespace as YAML for later processing.",
    )
    parser.add_argument(
        "-l",
        "--load",
        action="store_true",
        default=False,
        help="Load namespace from YAML for visualisation.",
    )
    parser.add_argument(
        "-k",
        "--insecure",
        action="store_true",
        default=False,
        help="Do not verify cluster SSL certificate.",
    )

    args = parser.parse_args()
    main(args)


if __name__ == "__main__":
    parse_args()

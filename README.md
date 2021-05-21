# Kubesurveyor  

Good enough Kubernetes namespace visualization tool.  
No provisioning to a cluster required, only Kubernetes API is scrapped.  

<img src='https://github.com/viralpoetry/kubesurveyor/raw/main/kubesurveyor.jpg'/>

## Installation    
```
sudo apt-get install graphviz
pip install kubesurveyor
```

## Usage

Export path to a custom certification authority, if you use one for your Kubernetes cluster API
```
export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
```

Alternatively, ignore K8S API certificate errors using `--insecure` or `-k`
```
kubesurveyor <namespace> --insecure
```

Show `<namespace>` namespace as a `dot` language graph, using currently active K8S config context  
```
kubesurveyor <namespace>
```

Specify context to be used, if there are multiple in the K8S config file  
```
kubesurveyor <namespace> --context <context>
```

Dump crawled namespace data to a `YAML` format for later processing
```
kubesurveyor <namespace> --context <context> --save > namespace.yaml
```

Load from `YAML` file, show as `dot` language graph
```
cat namespace.yaml | kubesurveyor <namespace> --load
```

Load from `YAML` file and render as `png` visualization to a current working directory
```
cat namespace.yaml | kubesurveyor <namespace> --load --out png
```

If you want to generate architecture image from `dot` definition by hand, use `dot` directly
```
dot -Tpng k8s.dot > k8s.png
```

Limitations:  
 - unconnected pods, services are not shown  
 - could have problems with deployments created by Tiller  
 - number of replicas is not tracked  

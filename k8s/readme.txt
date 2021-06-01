# Deploy SSPL in Docker & Kubernetes

# Step 0
Update machine-id, bmc secret in all configuration files 

# Step 1
Run ansible playbook to setup docker and kubernetes cluster
ansible-playbook ansible_single_node.yaml --flush-cache

For more details https://github.com/geerlingguy/ansible-role-kubernetes

# Step 2 
Create docker image for SSPL
docker build -t sspl -f Dockerfile

# Step 3
Create kubernetes deployment for SSPL
kubectl apply -f sspl.yaml

Verfiy if pod is created and running
kubectl get pods

# Step 4
Start a terminal session within kubernetes container and do your experiments
kubectl exec -it <pod-name> -- bash
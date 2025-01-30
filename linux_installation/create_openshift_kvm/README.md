This repo holds playbooks and roles related to the standing up and tearing down of an OpenShift cluster using KVM.
This assumes RHEL hosts for the KVM host, but in theory should work for other distributions. 

For DNS, I made the role for pfSense, although this should be easy to swap out for the backend of your choice.

Sushy-tools is installed to provide the RedFish functionality for BMC emulation for KVM. 


> [!IMPORTANT]
> I have several PRs open with upstream community.libvirt ansible module in order to implement the ability to get Mac Addresses
> As well as supporting the removal of backing storage for a VM when a VM is undefined. These changes are in [my fork](https://github.com/stratus-ss/community.libvirt/tree/all_changes) and you may need to use 
>```
>ansible-galaxy git+https://github.com/stratus-ss/community.libvirt/tree/all_changes
>```
> in the event the PRs [#190](https://github.com/ansible-collections/community.libvirt/pull/190) and [#191](https://github.com/ansible-collections/community.libvirt/pull/191) have not been merged at the time you go to use these utilities.

The templates directory has templates for VMs using legacy boot mode as opposed to UEFI. Edit the `vm_template.xml.j2` if you wish to change this. In addition, the `install-config.yaml` is a basic version of a baremetal installation. It assumes that the first network device will be used for installation purpose. At this time, the value `enp1s0` is assumed to be the first interface but there may be a predictive naming task(s) implemented in the future.

> [!NOTE]
> I am assuming hashicorp vault open source edition is available to store a versioned copy of the `install-config.yaml` so that you can reference it in the future.


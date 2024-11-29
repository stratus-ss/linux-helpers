ansible-galaxy collection install kewlfft.aur
mv ansible.log ansible_install.log
time ansible-playbook -v tasks/stage2.yaml

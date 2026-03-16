PYTHONPATH=/usr/lib/python3.14/site-packages:/usr/lib/python3.13/site-packages ansible-galaxy collection install kewlfft.aur
mv ansible.log ansible_install.log
time PYTHONPATH=/usr/lib/python3.14/site-packages:/usr/lib/python3.13/site-packages ansible-playbook -v tasks/stage2.yaml

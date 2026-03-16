mount -o remount,size=4G /run/archiso/cowspace
mount -t nfs -o vers=3 192.168.99.95:/storage/backups/pacman_cache /var/cache/pacman/pkg
pacman-key --init
pacman-key --populate archlinux
pacman -Sy archlinux-keyring --noconfirm
# Skip full system upgrade to avoid OOM issues
# pacman -Su --noconfirm
pacman -Sy ansible --noconfirm
# Install required Ansible collections (community.general, community.crypto, ansible.posix)
ansible-galaxy collection install community.general community.crypto ansible.posix --force
time PYTHONPATH=/usr/lib/python3.14/site-packages:/usr/lib/python3.13/site-packages ansible-playbook -v tasks/stage1.yaml

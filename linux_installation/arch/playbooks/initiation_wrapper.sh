mount -o remount,size=2G /run/archiso/cowspace
mount -t nfs 192.168.1.1:/storage/backups/pacman_cache /var/cache/pacman/pkg
pacman -Sy ansible --noconfirm
ansible-playbook -v stage1.yaml

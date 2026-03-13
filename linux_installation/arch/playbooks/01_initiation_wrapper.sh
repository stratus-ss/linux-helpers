mount -o remount,size=2G /run/archiso/cowspace
mount -t nfs -o vers=3 192.168.99.95:/storage/backups/pacman_cache /var/cache/pacman/pkg
pacman-key --init
pacman-key --populate archlinux
pacman -Sy ansible --noconfirm
time ansible-playbook -v tasks/stage1.yaml

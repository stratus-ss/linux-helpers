# Arch Linux Installation - Ansible Playbooks

These playbooks automate Arch Linux installation with support for:
- **ZFS on root** using ZFSBootMenu (UEFI only)
- **Traditional filesystems** (ext4, xfs, btrfs, bcachefs) using GRUB bootloader (UEFI or BIOS)

## Prerequisites

### For ZFS Installation

**⚠️ IMPORTANT:** If you want to use ZFS on root (`use_zfs: true`), you **MUST** boot from an **ArchZFS ISO** that has ZFS support built-in.

**Download ArchZFS ISO:**
- Latest releases: https://github.com/eoli3n/archiso-zfs/releases
- Build your own: https://github.com/eoli3n/archiso-zfs

The standard Arch Linux ISO does **NOT** include ZFS support. If you boot from a standard ISO and try to install ZFS, the playbook will detect this and exit with a helpful error message.

### For Traditional Filesystems (ext4, xfs, btrfs, bcachefs)

Use the standard Arch Linux ISO from https://archlinux.org/download/

## Quick Start

This guide assumes you have booted into the appropriate ISO and have a network connection.

**⚠️ IMPORTANT:** The install is split into stages because you will need to `chroot` into your `pac-strap` environment (mounted at `/mnt`). Once in the `chroot` you will find the playbooks copied to `/mnt` where you can then launch the `02_install_wrapper.sh`

## Before You Begin

- Know your target disk device (e.g., `/dev/sda`, `/dev/nvme0n1`)
  
- Have your desired username and password ready
  
- (Optional) Have NFS pacman cache available
  

## Perform Installation

1. **Clone the Repository:**
  Clone this repository to your home directory.
  
  ```bash
  git clone <repository_url> ~/linux-helpers
  cd ~/linux-helpers/linux_installation/arch/playbooks
  ```
  
2. **Configure Variables:**
  Open `vars.yaml` and configure the variables to match your system and preferences. At a minimum, you **must** set the following:
  
  - `device_name`: Target disk device (e.g., `/dev/sda`, `/dev/nvme0n1`)
  - `username`: Your desired username
  - `user_password`: Your user password
  - `luks_passphrase`: LUKS encryption passphrase (if using LUKS)
  - `luks_volume_name`: LUKS volume name (default: `cryptroot`)
  
  Optional variables control features like:

  - `use_zfs`: Use ZFS filesystem (default: true)
  - `filesystem_type`: Filesystem for non-ZFS installs (`ext4`, `xfs`, `btrfs`, `bcachefs`)
  - `boot_mode`: Boot mode (`uefi` or `bios`, default: `bios`)
  - `desktop`: Enable desktop installation
  - `desktop_name`: Desktop environment (`cinnamon`)
  - `libvirt`: Install virtualization support
  - `nvidia_lts`: Install NVIDIA LTS drivers
  - `nvidia_open`: Install NVIDIA open-source drivers
  - `nvidia_dkms`: Install NVIDIA DKMS drivers
  - `install_qemu_guest_agent`: Install QEMU guest agent for VMs (default: true)
  - `install_rustdesk`: Install RustDesk remote desktop (default: false)
  - `gaming_platform`: Install Steam and Lutris for gaming (default: false)
  - `use_luks`: Enable LUKS encryption
  - `network_pacman_cache`: Use network pacman cache
  - `nfs_path`: NFS path for pacman cache
  - `remote_server`: IP address of remote server for keys/configs
  - `enable_endeavour`: Enable EndeavourOS Cinnamon customizations
  - `flatpak`: Install Flatpak support
  - `faillock_increase`: Increase faillock retries (default: true)
  - `faillock_retries`: Number of login retries (default: 6)
  - `sudoers_suspend_no_passwd`: Allow suspend without password (default: false)
  - `old_pacman_version`: Use compatibility for older pacman versions
  - `add_ssh_key`: Enable SSH key setup (default: false)
  - `ssh_key_source`: Method for SSH key: `"string"`, `"file"`, or `"url"`
  - `ssh_public_key`: SSH public key as string (when `ssh_key_source: "string"`)
  - `ssh_key_file_path`: Path to local SSH key file (when `ssh_key_source: "file"`)
  - `ssh_key_url`: URL to download SSH key from (when `ssh_key_source: "url"`)

### SSH Key Setup

The playbooks support adding SSH public keys to the new user's authorized_keys file during installation. This enables passwordless SSH access after the system boots.

**To enable SSH key setup, set `add_ssh_key: true` in `vars.yaml`.**

There are three methods for providing the SSH public key:

1. **String variable method:**
   ```yaml
   add_ssh_key: true
   ssh_key_source: "string"
   ssh_public_key: "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC..."
   ```

2. **File path method:**
   ```yaml
   add_ssh_key: true
   ssh_key_source: "file"
   ssh_key_file_path: "/path/to/id_rsa.pub"
   ```
   This copies the key file from the local system to the new user's authorized_keys.

3. **URL method:**
   ```yaml
   add_ssh_key: true
   ssh_key_source: "url"
   ssh_key_url: "https://example.com/ssh-key.pub"
   ```
   This downloads the SSH key from the specified URL.

**Notes:**
- This feature is independent of the existing `restore_user_cryptography` remote server feature
- Both features can work independently or together
- Proper SSH directory permissions (0700) and file permissions (0600) are set automatically
- The feature is completely optional - default is disabled (`add_ssh_key: false`)
  
  **Filesystem Recommendations:**
  - `ext4`: Most stable, best for VMs and production (no snapshots)
  - `xfs`: High performance for large files, cannot shrink partitions
  - `btrfs`: Snapshots, compression, CoW - good ZFS alternative
  - `bcachefs`: Newest, experimental - testing only

3. **Run Stage 1 (from Arch ISO):**
  Execute the first wrapper script. This will partition your disk, set up ZFS, and install the base system.
  
  ```bash
  ./01_initiation_wrapper.sh
  ```
  
4. **Enter the New System:**
  After Stage 1 completes, `chroot` into the newly installed system.
  
  ```bash
  arch-chroot /mnt
  cd /mnt 
  ```
  
5. **Run Stage 2 (from `arch-chroot`):**
  Execute the second wrapper script from within the `chroot`. This will configure the operating system, install packages, and set up your user.
  
  ```bash
  ./02_install_wrapper.sh
  ```
  
6. **Finalize and Reboot:**
  The `final_stage.yaml` playbook should run automatically at the end of Stage 2 to unmount everything and reboot. If it doesn't, you may need to run it manually.
  
  ```bash
  ansible-playbook tasks/final_stage.yaml
  ```
  
7. **Post-Installation (Optional):**
  After rebooting and logging into your new system, you can run the `post-install.yaml` playbook to restore application settings and install Flatpaks.
  
  ```bash
  ansible-playbook post-install.yaml
  ```
  

## How This Works Under The Hood

### Prerequisites

The below steps are taken care of by the `01_initiation_wrapper.sh`. The below is an explanation of how Ansible is achieving the system setup.

### Expand Cowspace

For some computers, you may need to expand the `cowspace` so that Ansible has enough space to run.

```bash
mount -o remount,size=4G /run/archiso/cowspace
```

### Initialize Pacman Keyring

Initialize and populate the Arch Linux keyring to ensure package verification works:

```bash
pacman-key --init
pacman-key --populate archlinux
pacman -Sy archlinux-keyring --noconfirm
```

### Install Ansible

You also need to install Ansible. If you have a networked `pacman` cache, you can mount it first.

```bash
mount -t nfs -o vers=3 192.168.99.95:/storage/backups/pacman_cache /var/cache/pacman/pkg
pacman -Sy ansible --noconfirm
```

### Install Required Ansible Collections

Install the necessary Ansible collections for the playbooks:

```bash
ansible-galaxy collection install community.general community.crypto ansible.posix --force
```

> **IMPORTANT:**
> At the time of creation, the `zfs-linux-lts` package had a dependency on an LTS kernel that was only available in `[core-testing]`. These playbooks enable this repository for the ZFS installation and then disable it afterward.

## Playbook Workflow

The installation is split into multiple stages due to the `arch-chroot` process. The playbooks are designed to be run in order. Configuration is handled by editing `vars.yaml`.

### 1. `01_initiation_wrapper.sh`

This script kicks off the `tasks/stage1.yaml` playbook from the live Arch ISO environment.

- Expands the `cowspace` to 4G.
- Mounts the network `pacman` cache using NFS v3 (if available).
- Initializes and populates the Arch Linux pacman keyring.
- Updates the archlinux-keyring package.
- Installs Ansible.
- Installs required Ansible collections (community.general, community.crypto, ansible.posix).
- Configures PYTHONPATH for Python 3.13/3.14 compatibility.
- Calls `tasks/stage1.yaml`.

### 2. `tasks/stage1.yaml`

This playbook handles the initial disk setup.

- Partitions the target disk and optionally sets up LUKS encryption.
- Calls `tasks/pre-installation_zfs_setup.yaml` to create the ZFS pool and datasets.
- Installs the base Arch Linux system into `/mnt`.
- Copies the playbook directory to `/mnt/mnt` so it's available inside the `chroot`.

> **IMPORTANT:** After this playbook runs, you must `arch-chroot /mnt` and `cd /mnt` to run the next stage.

### 3. `02_install_wrapper.sh`

This wrapper script is run from inside the `chroot` environment.

- Installs the `kewlfft.aur` Ansible collection, which is needed to manage AUR packages.
- Calls `tasks/stage2.yaml`.

### 4. `tasks/stage2.yaml`

This is a simple wrapper playbook that loads variables from `vars.yaml` and calls `tasks/system-setup.yaml`. It is not meant to be edited directly.

### 5. `tasks/system-setup.yaml`

This is the main configuration playbook for the new system.

- Creates a user and configures `sudo` access.
- Sets up system locale and timezone.
- Installs `yay` (an AUR helper).
- Calls `tasks/final-install-zfs.yaml` to configure ZFS within the new system.
- Optionally installs `libvirt` for virtualization.
- Calls `tasks/desktop.yaml` if `desktop: true` is set in `vars.yaml`.

### 6. Filesystem Setup Playbooks

The installation supports multiple filesystem options:

#### `tasks/pre-installation_zfs_setup.yaml` (when `use_zfs: true`)

- Loads the ZFS kernel module.
- Creates the ZFS pool with optimized settings.
- Creates ZFS datasets for root and home.
- Handles LUKS encryption if enabled.
- Mounts the datasets and sets up ZFS cache.

#### `tasks/pre-installation_in_kernel_fs.yaml` (when `use_zfs: false` and `filesystem_type: ext4/xfs/btrfs`)

- Installs required filesystem tools (xfsprogs, btrfs-progs).
- Formats root partition with selected filesystem.
- Creates btrfs subvolumes (@ for root, @home for home) if using btrfs.
- Mounts filesystem with optimized options.
- Sets up compression for btrfs.

#### `tasks/pre-installation_bcachefs.yaml` (when `use_zfs: false` and `filesystem_type: bcachefs`)

- Installs bcachefs-tools and bcachefs-dkms.
- Loads bcachefs kernel module.
- Formats partition with bcachefs (with compression and checksums).
- Mounts bcachefs filesystem.
- **Note:** bcachefs is experimental; use for testing only.

### 7. `tasks/install-grub.yaml`

This playbook installs and configures the GRUB bootloader for non-ZFS installations. It supports both UEFI and BIOS boot modes.

- Installs GRUB, efibootmgr (for UEFI), and os-prober packages.
- For UEFI systems: Installs GRUB to the EFI system partition at `/boot`.
- For BIOS systems: Installs GRUB to the MBR of the target disk.
- Configures GRUB settings including timeout and os-prober.
- Handles LUKS encryption parameters in GRUB command line if enabled.
- Supports optional kernel parameters for hardware fixes (touchpad, AMD GPU).
- Generates the GRUB configuration file.
- **Note:** This playbook is only called when `use_zfs: false`; ZFS installations use ZFSBootMenu instead.

### 8. `tasks/final-install-zfs.yaml`

This playbook configures ZFS, ZFSBootMenu, and related services after system installation.

- Installs `zfs-linux-lts` and `efibootmgr`.
- Configures `mkinitcpio.conf` and generates the initramfs.
- Installs and configures `sanoid` for automated snapshots.
- Creates an EFI boot entry using `efibootmgr`.
- **Note:** This playbook is only called when `use_zfs: true`.

### 9. `tasks/desktop.yaml`

Installs and configures a desktop environment and common applications.

- Installs generic packages like Firefox, Steam, and Flameshot.
- Pulls user-specific configurations (SSH keys, GPG keys, VPN settings) from a remote server.
- Calls a desktop-specific playbook (`cinnamon.yaml`) based on the `desktop_name` variable in `vars.yaml`.

### 10. `tasks/cinnamon.yaml`

- Installs the Cinnamon desktop environment and related applications.
- Enables the `lightdm` display manager.
- Configures themes and autostart applications.

### 11. `tasks/final_stage.yaml`

This is the final playbook that cleans up the installation environment.

- Unmounts all partitions from `/mnt`.
- Exports the `zpool`.
- Reboots the system into the new Arch Linux installation.

## Post-Installation and Utility Playbooks

### `post-install.yaml`

This playbook is designed to be run after you have successfully booted into and logged into your new system. It restores application settings and installs a list of common Flatpak applications.

### `tasks/backup_configs.yaml`

This is a utility playbook for backing up user configuration files (`dconf` settings, Flatpak data, `.gnupg` directory, etc.) to a remote server. It is not used during the OS installation.
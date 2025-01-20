This Template will install apache, grab certificates, and create vhost entries for reverse proxy into containers.

In AWX, the following extra variables are used:

```
apache_install: true
apache_packages:
  - httpd
  - mod_ssl
vhosts:
  - name: transcribe.example.com
    cert_file_location: '{{ cert_dir }}/cert.pem'
    cert_key_file_location: '{{ cert_dir }}/privkey.pem'
    app_port: 8082
  - name: home.example.com
    cert_file_location: '{{ cert_dir }}/cert.pem'
    cert_key_file_location: '{{ cert_dir }}/privkey.pem'
    app_port: 5000
  - name: e2a.example.com
    cert_file_location: '{{ cert_dir }}/cert.pem'
    cert_key_file_location: '{{ cert_dir }}/privkey.pem'
    app_port: 7860
base_domain: '{{ requested_domain | regex_replace(''^\*\.'', '''') }}'
cert_dir: /etc/letsencrypt/live/{{ base_domain }}
vault_addr: https://vault.example.com
vault_path: certificates/data/{{ base_domain }}
```

In addition to this, there are 2 survey questions:

|Question|Variable|Default|
|--------|--------|-------|
|Hostname|apache_host|containers-gpu.example.com|
|Domain Cert To Use|requested_domain|*.example.com|

> [!IMPORTANT]
> The vault_read_certificates role needs to have credentials setup in AWX. I am using a custom credential-type for Vault KV lookup with following input config
> ```
> fields:
>   - id: vault_server
>     type: string
>     label: Vault Server URL
>   - id: vault_role_id
>     type: string
>     label: Role ID
>   - id: vault_secret_id
>     type: string
>     label: Secret ID
>     secret: true
> required:
>   - vault_server
>   - vault_role_id
>   - vault_secret_id
> ```
> And the following Injectory Configuration
> ```
> env:
>   VAULT_ADDR: '{{ vault_server }}'
>   VAULT_ROLE_ID: '{{ vault_role_id }}'
>   VAULT_SECRET_ID: '{{ vault_secret_id }}'
> extra_vars:
>   ansible_hashi_vault_url: '{{ vault_server }}'
>   ansible_hashi_vault_role_id: '{{ vault_role_id }}'
>   ansible_hashi_vault_secret_id: '{{ vault_secret_id }}'
>   ansible_hashi_vault_auth_method: approle
> ```
> You then need to create a new credntial in AWX which contains the vault URL, the Role ID and the Secret ID
> In addition you need to have the following pip packages: `hvac jmespath xmltodict lxml`
> Depending on your system you may need to install the Ansible collections `community.general community.hashi_vault community.crypto ansible.utils`


> [!NOTE] 
> These tasks assume firewalld. If the service is found to be active, it will open the appropriate port. Otherwise, it assumes there is no firewall enabled.

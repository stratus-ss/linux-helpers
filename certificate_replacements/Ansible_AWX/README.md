# renew_letsencrypt_namecheap.yaml
This playbook uses roles in order to do better error handling and has been tested on 6 domains, including a wild card domain.

> [!NOTE]
> For whatever reason the Vault UI on the opensource version does not show the wild card cert. However if you use the UI
> ```
> vault kv list certificates/
> Keys
> ---
> example.com
> ```
> In if you need to delete this you need to delete the data and the metadata `vault kv delete certificates/example.com` `vault kv metadata delete certificates/example.com` or some remnants will stay behind causing you problems

> [!IMPORTANT]
> You may want to create a survey to define the required variable `requested_domain`. Otherwise you will need to define it in the Extra Vars section


> [!WARNING]
> This playbook is using the LetsEncrypt _STAGING_ environment that will not issue real certs. The Production URL is commented out in both the certificate_management role and in the main playbook itself

## Intended for use with AWX

This should be easily modifiable for ansible core, but it has been written and tested on AWX

The template variables look like this:

```
base_domain: '{{ requested_domain | regex_replace(''^\*\.'', '''') }}'
cert_dir: /etc/letsencrypt/live/{{ base_domain }}
certbot_host: upload.example.com
email: admin@example.com.com
dns_resolution_retries: 5
dns_retry_interval: 20
dns_wait_time: 1
key_rotation_days: 45
letsencrypt_url: >-
  {% if letsencrypt_directory=='Production'
  %}https://acme-v02.api.letsencrypt.org/directory{% else
  %}https://acme-staging-v02.api.letsencrypt.org/directory{% endif %}
is_wildcard: '{{ requested_domain.startswith(''*.'') }}'
namecheap_api_user: stratusss
namecheap_username: stratusss
namecheap_api_key: >-
  {{ lookup('community.hashi_vault.hashi_vault',
  'secret=shared_tokens/data/registrar:namecheap_api_key', ) }}
namecheap_whitelisted_ip: 184.83.200.19
vault_addr: https://vault.example.com
vault_data:
  certificate: '{{ cert_dir }}/fullchain.pem'
  private_key: '{{ cert_dir }}/privkey.pem'
vault_path: certificates/data/{{ base_domain }}
```

> [!WARNING]
> the `requested_domain` was done in a survey as could optionally `force_renewal` and `letsencrypt_directory`. The if you want a wild card, be sure to put `*.mydomain.com` in the `requested_domain`.


The expectation is that there is a hashicorp vault instance available to check certificates into and out of the KV store.

The `ansible_hashi_vault_role_id` and `ansible_hashi_vault_secret_id` are defined in a custom credential type that has this for its input configuration:

```
fields:
  - id: vault_server
    type: string
    label: Vault Server URL
  - id: vault_role_id
    type: string
    label: Role ID
  - id: vault_secret_id
    type: string
    label: Secret ID
    secret: true
required:
  - vault_server
  - vault_role_id
  - vault_secret_id
```

And this for its injector configuration:

```
env:
  VAULT_ADDR: '{{ vault_server }}'
  VAULT_ROLE_ID: '{{ vault_role_id }}'
  VAULT_SECRET_ID: '{{ vault_secret_id }}'
extra_vars:
  ansible_hashi_vault_url: '{{ vault_server }}'
  ansible_hashi_vault_role_id: '{{ vault_role_id }}'
  ansible_hashi_vault_secret_id: '{{ vault_secret_id }}'
  ansible_hashi_vault_auth_method: approle
```

A credential is then created (in this case Vault API Token Lookup) that has the server url, approle role_id and approle secrect_id defined. In addition, I am using API v2 with a `path to auth` of approle


## AIO Playbook

This was my first attempt to get something working. I leave it here for reference. It has very little error checking, but was the first successful attempt in a limited subset of tests

# update_reolink_cameras.yaml

This playbook logs into a reolink camera, clears the existing certificates, fetches new certificates from Hashi Vault and then uploads them to the Reolink Cameras.

## Intended for use with AWX

This playbook uses the same lookup credentials as *renew_letsencrypt_namecheap.yaml* and therefore should have the credentials section of the template filled with the appropriate creds. The following `extra_vars` section should be included:

```
base_domain: '{{ requested_domain | regex_replace(''^\*\.'', '''') }}'
base_url: https://{{ inventory_hostname }}
cert_dir: /tmp/{{ base_domain }}
password: >-
  {{ lookup('community.hashi_vault.hashi_vault',
  'secret=camera_login/data/reolink:password', ) }}
username: >-
  {{ lookup('community.hashi_vault.hashi_vault',
  'secret=camera_login/data/reolink:username', ) }}
vault_path: certificates/data/{{ base_domain }}
```

I also included a survey that fills in `requested_domain` in case I ever want to change the domain
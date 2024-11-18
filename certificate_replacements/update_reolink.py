#!/usr/bin/env python3
"""
I wanted to replace the self-signed certificate with one signed by Let's Encrypt, and
did not want to perform this action manually.

I asked Reolink technical support, but they answered there is no API to manage certificates.

So I did some research and found the Reolink doorbell camera and probably other models 
do support to upload your own certificates. 

In developer tools I checked the API and found the annoying client side AES encryption 
implementation where the key is generated/ rotated in the script during login.

To reveal the key and iv, I simply set a breakpoint on the login logic and have the `e` and `t` values.

To decrypt the JSON payload I wrote the script below:

--------------------------------------------------------------------------------
#!/usr/bin/env python3

from crypto.Cipher import AES
import base64

#e = "B642D317BD521D58", t = "0D6A4261FCD46185"
key = b"B642D317BD521D58"
iv = b"0D6A4261FCD46185"

encrypted_payload = "Plha/2eKtaMXwqNXZAlawvZB88qw3KdkRpLrMRol2nh1EmKPQJN****"

decipher = AES.new(key, AES.MODE_CFB, IV=iv, segment_size=128)

decrypted_payload = decipher.decrypt(base64.b64decode(encrypted_payload))

print(decrypted_payload.decode("UTF-8"))

--------------------------------------------------------------------------------

Now I know the endpoints and payload of API requests.

Important notes:
The webservice in the doorbell camera only supports RSA certificates and not EC (Elliptic Curve, ec256 for example).
If you use this script the certificate and key filenames are hardcoded to `server.crt` and `server.key`,
but during testing I found using filenames that contains the FQDN the API fails. 

Next, you need a certificate and key.

I use Cloudflare as DNS provider, and prefer Lego as ACME client.

To request the certificate from Let's Encrypt I used the Lego container image below:

docker run \
    -v "$(pwd)/.lego:/.lego" \
    -e "CF_DNS_API_TOKEN=***" \
    goacme/lego \
    --key-type="rsa4096" \
    --accept-tos \
    --email="***" \
    --domains="***" \
    --dns="cloudflare" \
    run

Next step is to update some values in the script below, schedule this
script to run periodically after the docker run above and 
enjoy automatic certificate updates/ rotation.

"""

import requests
import os
import base64
import time
import ssl
import sys
import argparse
import urllib3
# I am choosing to disable the URL SSL cert warnings as the whole purpose of this script is 
# to update or replace invalid certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
urllib3.disable_warnings()


parser = argparse.ArgumentParser(description="A script that uses base_url")
parser.add_argument(
        "--base_url",
        type=str,
        help="The base URL for the application"
    )

    # Parse arguments
args = parser.parse_args()

os.environ['no_proxy'] = '*' 

print(args.base_url)
base_url = args.base_url
username = "admin"
password = "<password>"

certificate_path = "/certificates/example.com/cert.crt"
key_path = "/certificates/example.com/privkey.key"

class Reolink(object):
    def __init__(self, **kwargs):
        self.base_url = kwargs.pop('base_url', None)
        self.username = kwargs.pop('username', None)
        self.password = kwargs.pop('password', None)
        self.token = None
        
    def login(self):
        login_req = [{"cmd":"Login",
                    "param": {"User": {"userName": self.username,
                                        "password": self.password}
                                        }
                                }
                    ]

        url = f'{self.base_url}/cgi-bin/api.cgi?cmd=Login'

        login_resp = requests.post(url=url, json=login_req, verify=False)
        login_data = login_resp.json()

        self.token = login_data[0]['value']['Token']['name']

        print(f"Login was succesfull, got token: {self.token}")
        return self.token
    
    def verify_ssl_certificate(self):
        try:
            response = requests.get(self.base_url)
            response.raise_for_status()
            print(f"Certificate for {self.base_url} is valid.")
            return True
        except ssl.SSLCertVerificationError as err:
            print(f"Certificate verification failed for {self.base_url}, error: {err}", file=sys.stderr)
            return False
        
    def clear_certs(self):
        
        url = f"{self.base_url}/cgi-bin/api.cgi?cmd=CertificateClear&token={self.token}"
        clear_req = [{
            "cmd": "CertificateClear",
            "action": 0,
            "param": {}
        }]

        clear_certs_resp = requests.post(url=url, json=clear_req, verify=False)
        clear_certs_data = clear_certs_resp.json
        print(clear_certs_data)
        return clear_certs_data

    
    def update_certs(self, certificate_path, key_path):
        crtfile_stats = os.stat(certificate_path)
        crt_filesize = crtfile_stats.st_size

        with open(certificate_path, "rb") as crt_file:
            b64_crt = base64.b64encode(crt_file.read())
            
        keyfile_stats = os.stat(key_path)
        key_filesize = keyfile_stats.st_size

        with open(key_path, "rb") as key_file:
            b64_key = base64.b64encode(key_file.read())
            
        cert_req = [{
                    "cmd": "ImportCertificate",
                    "action": 0,
                    "param": {
                        "importCertificate": { 
                            "crt": {
                                "size": crt_filesize,
                                "name": "server.crt",
                                "content": b64_crt.decode("UTF-8")
                            },
                            "key": {
                                "size": key_filesize, 
                                "name": "server.key",
                                "content": b64_key.decode("UTF-8")
                            }
                        }
                    }
                    }
                    ]
        
        url = f"{self.base_url}/cgi-bin/api.cgi?cmd=ImportCertificate&token={self.token}"
        update_certs_resp = requests.post(url=url, json=cert_req, verify=False)
        update_certs_data = update_certs_resp.json
        
        return update_certs_data

    def logout(self):
        
        url = f"{self.base_url}/cgi-bin/api.cgi?cmd=Logout&token={self.token}"
        logout_resp = requests.get(url=url, verify=False)
        logout_data = logout_resp.json
        
        print(f"Logout was succesfull, got response: {logout_data}")
        return logout_data

def main():
    reolink = Reolink(base_url=base_url, 
                      username=username, 
                      password=password)
    
    reolink.login()

    reolink.clear_certs()

    # the doorbell will restart the internal web daemon
    time.sleep(15)
    reolink.login()

    reolink.update_certs(certificate_path=certificate_path, 
                         key_path=key_path)
    
    # the doorbell will restart the internal web daemon
    time.sleep(15)

    reolink.logout()

#    if not reolink.verify_ssl_certificate():
#        exit(1)

if __name__ == "__main__":
    main()
